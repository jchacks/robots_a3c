import tensorflow as tf

from utils import *

actor_learning_rate = 0.00025
critic_learning_rate = 0.001


def model(state_features, num_actions=5):
    state = tf.placeholder('float32', (None, 10, state_features), 'state')
    seq = tf.placeholder('int32', (None,), 'state_seq')

    with tf.variable_scope('model'):
        lstm_out, (out_state, z_state) = lstm(state, seq, [256], name='state')
        tf.summary.histogram('lstm_out', lstm_out)

        out = fully(lstm_out, 256, scope='1', activation=tf.nn.relu)
        out = fully(out, 128, scope='2', activation=tf.nn.relu)
        out = fully(out, num_actions, scope='out', activation=tf.nn.relu)
        policy = tf.tanh(out)

        out = fully(lstm_out, 128, scope='o1', activation=tf.nn.relu)
        out = fully(out, 64, scope='o2', activation=tf.nn.relu)
        value = fully(out, 1, activation=None, scope='out')

    return FeedFetch({
        'state': (state, seq),
    }, {
        'state_lstm': (lstm_out, out_state, z_state),
        'policy': policy,
        'value': value,
    })


def train(score_prediction):
    critic_lr = tf.placeholder_with_default(critic_learning_rate, (), 'actor_lr')
    actor_lr = tf.placeholder_with_default(actor_learning_rate, (), 'actor_lr')

    with tf.variable_scope('critic_loss'):
        score_target = tf.placeholder(tf.float32, [None, 1], 'score')
        critic_loss = tf.reduce_mean((score_target - score_prediction) ** 2)  # + critic_reg
        tf.summary.scalar('mse', critic_loss)
        train_critic = tf.train.AdamOptimizer(critic_lr).minimize(critic_loss,
                                                                  var_list=tf.trainable_variables('critic'))

    with tf.control_dependencies([train_critic]):
        with tf.variable_scope('actor_loss'):
            actor_loss = tf.reduce_mean((100 - score_prediction) ** 2)  # + self.actor_reg / 100000
            tf.summary.scalar('mse', actor_loss)
            train_actor = tf.train.AdamOptimizer(actor_lr).minimize(actor_loss,
                                                                    var_list=tf.trainable_variables('actor'))

    return FeedFetch({
        'score_target': score_target,
        'critic_lr': critic_lr,
        'actor_lr': critic_lr
    }, {
        'critic_minimizer': train_critic,
        'actor_minimizer': train_actor,
        'critic_loss': critic_loss,
        'actor_loss': actor_loss,
    })


def summary():
    return tf.summary.merge_all()


class Model(object):
    def __init__(self):
        self._model = model(11, 5)
        config = tf.ConfigProto(gpu_options=tf.GPUOptions(allow_growth=True))
        self._sess = tf.Session(config=config)
        self._saver = tf.train.Saver(tf.trainable_variables('actor'), save_relative_paths=True)

    def restore(self):
        chkp = tf.train.latest_checkpoint('./checkpoint/')
        print("Restoring chkp: %s " % (chkp,))
        self._saver.restore(self._sess, chkp)

    def run(self, data):
        return self._sess.run(self._model.fetch['action_prediction'], {self._model.feed['state']: data})
