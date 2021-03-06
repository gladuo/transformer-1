from __future__ import print_function
import yaml
import time
import os
import logging
from argparse import ArgumentParser
import tensorflow as tf

from utils import DataUtil, AttrDict
from model import Transformer
from evaluate import Evaluator


def train(config):
    logger = logging.getLogger('')

    """Train a model with a config file."""
    du = DataUtil(config=config)
    model = Transformer(config=config, devices=config.train.devices)
    model.build_train_model()

    sess_config = tf.ConfigProto()
    sess_config.gpu_options.allow_growth = True
    sess_config.allow_soft_placement = True

    summary_writer = tf.summary.FileWriter(config.train.logdir, graph=model.graph)

    with tf.Session(config=sess_config, graph=model.graph) as sess:
        try:
            model.saver.restore(sess, tf.train.latest_checkpoint(config.train.logdir))
        except:
            # Initialize all variables.
            sess.run(tf.global_variables_initializer())
            logger.info('Failed to reload model.')

        evaluator = Evaluator()
        evaluator.init_from_existed(model, sess, du)

        dev_bleu = evaluator.evaluate(**config.dev)
        toleration = config.train.toleration
        for epoch in range(1, config.train.num_epochs+1):
            for batch in du.get_training_batches_with_buckets():
                start_time = time.time()
                step = sess.run(model.global_step)
                # Summary
                if step % config.train.summary_freq == 0:
                    step, lr, gnorm, loss, acc, summary, _ = sess.run(
                        [model.global_step, model.learning_rate, model.grads_norm,
                         model.loss, model.accuracy, model.summary_op, model.train_op],
                        feed_dict={model.src_pl: batch[0], model.dst_pl: batch[1]})
                    summary_writer.add_summary(summary, global_step=step)
                else:
                    step, lr, gnorm, loss, acc, _ = sess.run(
                        [model.global_step, model.learning_rate, model.grads_norm,
                         model.loss, model.accuracy, model.train_op],
                        feed_dict={model.src_pl: batch[0], model.dst_pl: batch[1]})
                logger.info(
                    'epoch: {0}\tstep: {1}\tlr: {2:.6f}\tgnorm: {3:.4f}\tloss: {4:.4f}\tacc: {5:.4f}\ttime: {6:.4f}'.
                    format(epoch, step, lr, gnorm, loss, acc, time.time() - start_time))

                # Save model
                if config.train.save_freq > 0 and step % config.train.save_freq == 0:
                    new_dev_bleu = evaluator.evaluate(**config.dev)
                    if new_dev_bleu >= dev_bleu:
                        mp = config.train.logdir + '/model_epoch_%d_step_%d' % (epoch, step)
                        model.saver.save(sess, mp)
                        logger.info('Save model in %s.' % mp)
                        toleration = config.train.toleration
                        dev_bleu = new_dev_bleu
                    else:
                        toleration -= 1
                        if toleration <= 0:
                            break

            # Save model per epoch if config.train.save_freq is less than zero
            if config.train.save_freq <= 0:
                new_dev_bleu = evaluator.evaluate(**config.dev)
                if new_dev_bleu >= dev_bleu:
                    mp = config.train.logdir + '/model_epoch_%d' % (epoch)
                    model.saver.save(sess, mp)
                    logger.info('Save model in %s.' % mp)
                    toleration = config.train.toleration
                    dev_bleu = new_dev_bleu
                else:
                    toleration -= 1
                    if toleration <= 0:
                        break

            if toleration <= 0:
                break
        logger.info("Finish training.")


if __name__ == '__main__':
    parser = ArgumentParser()
    parser.add_argument('-c', '--config', dest='config')
    args = parser.parse_args()
    # Read config
    config = AttrDict(yaml.load(open(args.config)))
    # Logger
    if not os.path.exists(config.train.logdir):
        os.makedirs(config.train.logdir)
    logging.basicConfig(filename=config.train.logdir+'/train.log', level=logging.DEBUG)
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    logging.getLogger('').addHandler(console)
    # Train
    train(config)
