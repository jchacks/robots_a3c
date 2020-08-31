import time

from baselines.a2c.utils import Scheduler

from utils import *


class Model(object):
    def __init__(self, state_features, num_actions=2, restore=True):
        self.is_training = 1.0
        self.global_step = tf.Variable(0, name="global_step", trainable=False)
        self.num_actions = num_actions

        self.ent_coef = 0.01
        self.vf_coef = 0.7 # 0.5 # default
        self.max_grad_norm = 0.5
        self.lr = 7e-4
        self.alpha = 0.99
        self.epsilon = 1e-5
        lrschedule = "linear"
        self.lr = Scheduler(v=self.lr, nvalues=80e6, schedule=lrschedule)

        self.model(state_features=state_features)
        self.loss()
        self.init()
        if restore:
            self.restore()
        self.summary()
        self.save_path = "checkpoint/model"

    def restore(self):
        chkp = tf.train.latest_checkpoint("./checkpoint")
        if chkp is not None:
            print("Restoring chkp: %s " % (chkp,))
            self._saver.restore(self._sess, chkp)

    def init(self):
        config = tf.ConfigProto(gpu_options=tf.GPUOptions(allow_growth=True))
        self._sess = tf.Session(config=config)
        self._sess.run(tf.global_variables_initializer())
        self._saver = tf.train.Saver(tf.trainable_variables(), save_relative_paths=True)
        self._summ_writer = tf.summary.FileWriter("./train/{0}".format(int(time.time())), self._sess.graph)

    def model(self, state_features):
        with tf.variable_scope("model"):
            self.X = state = tf.placeholder("float32", (None, state_features), "state")

            with tf.variable_scope("shared"):
                shared = fully(state, 128, scope="s1", summary_w=False, reg=True, activation=mish)
                shared = fully(shared, 128, scope="s2", summary_w=False, reg=True, activation=mish)

            with tf.variable_scope("actor"):
                out = fully(shared, 64, scope="a1", summary_w=False, reg=True, activation=mish)

                mu = fully(shared, 32, scope="a_mu", summary_w=True, reg=True, activation=mish)
                self.mu = mu = fully(mu, self.num_actions, scope="mu", summary_w=True, activation=tf.nn.tanh)
                tf.summary.histogram("mu", mu)

                chol = fully(out, 32, scope="a_chol", summary_w=False, reg=True, activation=mish)
                tf.summary.histogram("chol", chol)

                # chol_matrix = fully(chol, self.num_actions ** 2, scope='chol', summary_w=False, activation=None)
                # chol_matrix = tf.reshape(chol_matrix, (-1, self.num_actions, self.num_actions))
                # self.chol = chol = tfp.matrix_diag_transform(chol_matrix, transform=tf.nn.softplus)

                # self.normal_dist = tfp.MultivariateNormalTriL(mu, chol, allow_nan_stats=False)

                chol = fully(out, self.num_actions, scope="var", summary_w=False, reg=True, activation=None)
                self.normal_dist = tfp.distributions.Normal(
                    mu, tf.clip_by_value(tf.exp(chol), 1e-3, 50), allow_nan_stats=False
                )
                self.sampled_action = tf.clip_by_value(self.normal_dist.sample(), -1.0, 1.0)

            with tf.variable_scope("critic"):
                out = fully(shared, 64, scope="v1", summary_w=True, activation=mish)
                out = fully(out, 32, scope="v2", summary_w=True, activation=mish)
                self.value = fully(out, 1, summary_w=True, activation=None, scope="value")
                tf.summary.histogram("value", self.value)

    def loss(self):
        self.LR = tf.placeholder(tf.float32, [])
        self.advantage = advantage = tf.placeholder("float32", (None,), "advantage")
        self.action = action = tf.placeholder("float32", (None, self.num_actions), "action")
        self.td_target = tf.placeholder("float32", (None,), "td_target")

        tf.summary.scalar("lr", self.LR)
        tf.summary.histogram("advantage", self.advantage)
        tf.summary.histogram("action", self.action)
        tf.summary.histogram("td_target", self.td_target)

        # Actor loss
        self.log_prob = self.normal_dist.log_prob(action)
        pg_loss = tf.reduce_mean(-self.log_prob * advantage[:, tf.newaxis])
        tf.summary.scalar("pg_loss", pg_loss)
        self.entropy = entropy = tf.reduce_mean(self.normal_dist.entropy())
        tf.summary.scalar("entropy", self.entropy)

        reg_loss = 0  # -1e-2 * self.entropy
        self.pg_loss = pg_loss + reg_loss
        tf.summary.scalar("reg_loss", reg_loss)

        # Critic loss
        self.vf_loss = tf.reduce_mean((self.value - self.td_target) ** 2)
        tf.summary.scalar("vf_loss", self.vf_loss)

        self.loss = self.pg_loss + self.vf_loss * self.vf_coef - entropy * self.ent_coef

        # Optimiser
        tvars = tf.trainable_variables("model")
        grads, _ = tf.clip_by_global_norm(tf.gradients(self.pg_loss, tvars), self.max_grad_norm)
        optimiser = tf.train.RMSPropOptimizer(self.LR)
        self._train = optimiser.apply_gradients(zip(grads, tvars), global_step=self.global_step)

        # self.sig_loss = tf.reduce_mean(tf.nn.relu(self.sig - 0.5) ** 2)
        # self.mu_loss = tf.reduce_mean(self.mu ** 2) * 1e2

    def run(self, **kwargs):
        action, value = self._sess.run(
            [self.sampled_action, self.value],
            {
                self.X: kwargs["obs"],
            },
        )
        return action, value

    def test(self, obs):
        """
        Takes the mean prediction for each value
        :param kwargs:
        :return:
        """
        return self._sess.run(
            [self.mu, self.value],
            {
                self.X: obs,
            },
        )

    def train(self, obs, states, rewards, masks, actions, values):
        train_fetches = {
            "vf_loss": self.vf_loss,
            "pg_loss": self.pg_loss,
            "summary": self.summ,
            "minimiser": self._train,
            "step": self.global_step,
        }
        advs = rewards - values
        for step in range(len(obs)):
            cur_lr = self.lr.value()

        res = self._sess.run(
            train_fetches,
            {self.X: obs, self.LR: cur_lr, self.advantage: advs, self.td_target: rewards, self.action: actions},
        )

        self._summ_writer.add_summary(res["summary"], global_step=res["step"])
        if res["step"] % 100 == 0:
            self._saver.save(self._sess, self.save_path, global_step=res["step"])

        return res

    def get_value(self, obs):
        """
        Returns the value of state at obs
        :param obs:
        :return:
        """
        return self._sess.run(self.value, {self.X: obs})

    def summary(self):
        self.summ = tf.summary.merge_all()
        return self.summ