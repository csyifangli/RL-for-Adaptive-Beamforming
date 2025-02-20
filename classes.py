# -*- coding: utf-8 -*-
"""
@author: Nicolai Almskou & Victor Nissen
"""
import numpy as np
import math
import random
import tensorflow as tf
import tensorflow.keras.layers as kl

import helpers


class Track():
    def __init__(self, case, delta_t, r_lim, intersite, debug_print=False):
        self.delta_t = delta_t
        self.env = case["environment"]
        self.vpref = case["vpref"]
        self.vmax = case["vmax"]
        self.vmin = case["vmin"]
        self.pvpref = case["pvpref"]
        self.pvuni = 1 - np.sum(case["pvpref"])
        self.pvchange = self.delta_t / case["vchange"]
        self.pdirchange = self.delta_t / case["dirchange"]
        self.pdirchange_stop = case["stop_dirchange"]
        self.mu_s = case["static_friction"]
        self.acc_max = case["acc_max"]
        self.dec_max = case["dec_max"]
        self.ctmax = case["curvetime"]["max"]
        self.ctmin = case["curvetime"]["min"]

        self.v_target = 0
        self.a = 0

        self.curve_time = 0
        self.curve_dt = 0
        self.delta_phi = 0
        self.v_stop = False
        self.vrmax = 0
        self.curve_slow = 0

        self.radius_limit = r_lim

        # Debug msg
        self.debug_print = debug_print

        # Base Stations Coordinates
        self.intersite_bs = intersite
        self.pos_bs = self.get_bs_pos()

    def get_bs_pos(self):
        # Length to b and d on the x-axis
        hex_bd = np.sqrt((self.intersite_bs**2) - (self.intersite_bs/2)**2)

        # a
        a = np.array([0, 0])

        # b
        b = np.array([a[0] - hex_bd, self.intersite_bs/2])

        # d
        d = np.array([a[0] + hex_bd, self.intersite_bs/2])

        # c
        c = np.array([a[0], self.intersite_bs])

        return np.array([a, b, c, d]).T

    def set_acceleration(self, acc):
        if acc:
            return np.random.rand() * self.acc_max + 0.00001
        return - (np.random.rand() * self.dec_max + 0.00001)

    def change_velocity(self):
        p_uni = np.random.rand()
        p_pref = self.pvpref[0]
        l_pref = len(self.pvpref)

        # Checks if a pref. velocity should be chosen
        if p_uni < p_pref:
            return self.vpref[0]

        for i in range(1, l_pref):
            p_pref += self.pvpref[i]
            if (p_uni > p_pref - self.pvpref[i]) and (p_uni < p_pref):
                return self.vpref[i]

        # Return a velocity from a uniform dist. between set min and max
        return np.random.rand() * (self.vmax - self.vmin) + self.vmin

    def update_velocity(self, v):
        if np.random.rand() < self.pvchange:
            self.v_target = self.change_velocity()

            # Get an accelation / deccelation
            if self.v_target > v:
                self.a = self.set_acceleration(True)
            elif self.v_target < v:
                self.a = self.set_acceleration(False)
            else:
                self.a = 0

        # Update the velocity bases on target and accelation
        v = v + self.a * self.delta_t

        if (((self.a > 0) and (v > self.v_target)) or
                ((self.a < 0) and (v < self.v_target))):
            v = self.v_target
            self.a = 0

        return v

    def update_direction(self, phi, v):
        # "Stop-turn-and-go" implemented here
        if v == 0:
            # Only changes the target delta phi once
            if not self.v_stop:
                if np.random.rand() < self.pdirchange_stop:
                    if np.random.rand() < 0.5:
                        delta_phi_target = np.pi / 2
                    else:
                        delta_phi_target = -np.pi / 2
                else:
                    delta_phi_target = 0

                # Calculat the number of time step the change in direction needs
                self.curve_time = np.floor((np.random.rand() * (self.ctmax - self.ctmin) + self.ctmin) / self.delta_t)

                # Resets the tracker
                self.curve_dt = 0

                # Calculate the delta direction change per time step
                self.delta_phi = delta_phi_target / self.curve_time

                self.v_stop = True

        else:
            self.v_stop = False

            # Change target delta_phi, while the user is moving
            if np.random.rand() < self.pdirchange:
                # Calculat the number of time step the change in direction needs
                self.curve_time = np.floor((np.random.rand() * (self.ctmax - self.ctmin) + self.ctmin) / self.delta_t)

                # Resets the tracker
                self.curve_dt = 0

                # Target direction change
                delta_phi_target = (np.random.rand() * 2 * np.pi - np.pi)

                # Calculate the delta direction change per time step
                self.delta_phi = delta_phi_target / self.curve_time

                # Calculate the maximum radius
                rc = self.v_target * self.curve_time * self.delta_t / np.abs(delta_phi_target)

                # Calculate the maximum velocity which can be taken
                self.vrmax = np.sqrt(self.mu_s * 9.81 * rc)

                if self.v_target > self.vrmax:
                    self.v_target = self.vrmax

                if v > self.vrmax:
                    self.a = self.set_acceleration(False)

                    self.curve_slow = np.ceil(((v - self.vrmax) / np.abs(self.a)) / self.delta_t)
                else:
                    self.curve_slow = 0

            # Updates the direction based on the target delta phi
            if self.curve_dt < self.curve_time + self.curve_slow:
                if self.curve_dt >= self.curve_slow:
                    phi = phi + self.delta_phi

                    # Checks for overflow
                    phi = self.angle_overflow(phi)

                self.curve_dt += 1

        return phi

    def update_pos(self, pos, v, phi):
        # x-axis
        pos[0] = pos[0] + np.cos(phi) * v * self.delta_t

        # y-axis
        pos[1] = pos[1] + np.sin(phi) * v * self.delta_t

        return pos

    def angle_overflow(self, phi):
        # Checks for overflow
        if phi > np.pi:
            phi -= 2 * np.pi
        if phi < -np.pi:
            phi += 2 * np.pi

        return phi

    def initialise_run(self):
        # Velocity
        self.v_target = self.change_velocity()
        v = self.v_target

        # Position
        if self.env.lower() == "urban":
            c_idx = np.random.randint(0, 5)

            # Can spawn around the 4 BS and in the middle of the BS.
            if c_idx < 4:
                pos = np.random.uniform(-self.radius_limit / 2, self.radius_limit / 2, size=2) + self.pos_bs[:, c_idx]
            else:
                pos = (np.random.uniform(-self.radius_limit*0.75, self.radius_limit*0.75, size=2) +
                       np.array([0, self.intersite_bs/2]))

        elif self.env.lower() == "highway":
            # Choose a start position on the edge based on a random chosen angle
            egde_angle = (np.random.rand() * 2 * np.pi - np.pi)
            pos = self.radius_limit * np.array([np.cos(egde_angle), np.sin(egde_angle)])

        else:
            pos = np.array([0, 0])

        # Direction
        if self.env.lower() == "urban":
            phi = np.random.rand() * 2 * np.pi - np.pi

        elif self.env.lower() == "highway":
            # Limit the start direction so it does not go out of the circle at the start

            # Get the angle which points at the center
            dir_center = egde_angle + np.pi

            # Checks for overflow
            dir_center = self.angle_overflow(dir_center)

            # Draw from a uniform distribution around the center angle
            edge_max = np.pi / 6
            edge_min = -np.pi / 6
            phi = dir_center + np.random.rand() * (edge_max - edge_min) + edge_min

            # Checks for overflow
            phi = self.angle_overflow(phi)

        else:
            phi = 0

        return v, phi, pos

    def run(self, N):
        # Create a empty array for the velocities
        v = np.zeros([N])
        phi = np.zeros([N])
        pos = np.zeros([3, N])
        pos[2, :] = 1.5

        # Get start values
        v[0], phi[0], pos[0:2, 0] = self.initialise_run()

        # Start running the "simulation"
        t = 1
        i = 0
        while (t < N):
            pos[0:2, t] = self.update_pos(pos[0:2, t - 1], v[t - 1], phi[t - 1])

            # Checks if the positions is inside the search radius of minimum one of the base stations
            if np.sum(np.linalg.norm(pos[0:2, t] - self.pos_bs.T, axis=1) < self.radius_limit) == 0:
                # Restarts the run
                if self.debug_print:
                    print(f'number of tries: {i}')
                    print(f'How far we got: {t}')

                t = 1
                i += 1

                # Start with new values
                v[0], phi[0], pos[0:2, 0] = self.initialise_run()

            else:
                v[t] = self.update_velocity(v[t - 1])
                phi[t] = self.update_direction(phi[t - 1], v[t])
                t += 1

        return pos


class Model(tf.keras.Model):
    """
    Subclassing a multi-layered NN using Keras from Tensorflow
    """

    def __init__(self, num_states, hidden_units, num_actions, n_earlier_actions):
        super(Model, self).__init__()  # Used to run the init method of the parent class
        self.n_earlier_actions = n_earlier_actions

        self.input_layer = kl.InputLayer(input_shape=(num_states-self.n_earlier_actions,))

        self.embedding_layer = kl.Embedding(input_dim=num_actions, output_dim=1, input_length=1)

        self.hidden_layers = []

        for hidden_unit in hidden_units:
            self.hidden_layers.append(kl.Dense(hidden_unit, activation='tanh'))  # Left kernel initializer

        self.output_layer = kl.Dense(num_actions, activation='linear')

    @tf.function
    def call(self, inputs, **kwargs):
        x1 = self.input_layer(inputs[:, self.n_earlier_actions:])
        x2 = kl.Flatten()(self.embedding_layer(inputs[:, :self.n_earlier_actions]))
        x = kl.Concatenate()([x1, x2])
        for layer in self.hidden_layers:
            x = layer(x)
        output = self.output_layer(x)
        return output


class ReplayMemory():
    """
    Used to store the experience genrated by the agent over time
    """

    def __init__(self, capacity):
        self.capacity = capacity
        self.memory = []
        self.push_count = 0

    def push(self, experience):
        if len(self.memory) < self.capacity:
            self.memory.append(experience)
        else:
            self.memory[self.push_count % self.capacity] = experience
        self.push_count += 1

    def sample(self, batch_size):
        return random.sample(self.memory, batch_size)

    def can_provide_sample(self, batch_size):
        return len(self.memory) >= batch_size


class EpsilonGreedyStrategy():
    """
    Decaying Epsilon-greedy strategy
    """

    def __init__(self, start, end, decay):
        self.start = start
        self.end = end
        self.decay = decay

    def get_exploration_rate(self, current_step):
        return self.end + (self.start - self.end) * math.exp(-1*current_step*self.decay)


class DQN_Agent():
    """
    Used to take actions by using the Model and given strategy.
    """

    def __init__(self, strategy, num_actions):
        self.current_step = 0
        self.strategy = strategy
        self.num_actions = num_actions

    def select_action(self, state, policy_net):
        rate = self.strategy.get_exploration_rate(self.current_step)
        self.current_step += 1

        if rate > random.random():
            return random.randrange(self.num_actions), rate, True
        else:
            return np.argmax(policy_net(np.atleast_2d(np.atleast_2d(state).astype('float32')))), rate, False


class Environment():
    """
    Environment created from the QuaDRiga simulation
    """

    def __init__(self, W, F, Nt, Nr, Nbs, Nbt, Nbr,
                 r_r, r_t, fc, P_t, chunksize,
                 AoA, AoD, Beta, pos_log, ori_log,
                 n_earlier_actions, n_earlier_pos, n_earlier_ori):
        self.AoA = AoA
        self.AoD = AoD
        self.Beta = Beta
        self.pos_log = pos_log
        self.ori_log = ori_log

        # Chosen path taken from the pos_log
        self.pos = 0

        # Chosen oritations taken from ori_log
        self.ori = 0

        # Codebooks
        self.W = W
        self.F = F

        # Number of antennas
        self.Nt = Nt
        self.Nr = Nr

        # Number of basestations
        self.Nbs = Nbs

        # Action space
        self.action_space_n = Nbr*Nbs*Nbt

        # Antenna Posistions
        self.r_t = r_t
        self.r_r = r_r

        # Wavelength
        self.lambda_ = 3e8 / fc

        # Transmitted power
        self.P_t = P_t

        # Number of steps / step count
        self.nstep = chunksize
        self.stepnr = 0

        # Where the chunks starts and which mobility pattern is has been taken from
        self.stepstart = 0
        self.path = 0

        # What state we are in
        self.state = np.array([0.0, 0, 0, 0, 0])

        # Number of earlier action in the state space
        self.n_earlier_actions = n_earlier_actions

        # Number of earlier positions (included current pos) in the state space
        self.n_earlier_pos = n_earlier_pos

        # Number of earlier oritations (included current ori) in the state space
        self.n_earlier_ori = n_earlier_ori

        # Reward Matrix
        self.Reward_matrix = 0

    def create_reward_matrix(self):

        # Number of episodes / mobility patterns
        npaths = len(self.AoA)

        # Length of episodes / mobility patterns
        nsteps = np.shape(self.AoA[0])[1]

        # Initialise the matrix
        R = np.zeros((npaths, nsteps, self.Nbs*len(self.F[:, 0])*len(self.W[:, 0])))
        R_tmp = np.zeros((self.Nbs, len(self.F[:, 0]), len(self.W[:, 0])))

        for path in range(npaths):
            for step in range(nsteps):
                for b in range(self.Nbs):
                    # Get channel parameters
                    beta = self.Beta[path][0][b, step, :]

                    # Calculate steering vectors
                    alpha_rx = helpers.steering_vectors2d(direction=-1, theta=self.AoA[path][b, step, :],
                                                          r=self.r_r, lambda_=self.lambda_)
                    alpha_tx = helpers.steering_vectors2d(direction=1, theta=self.AoD[path][0][b, step, :],
                                                          r=self.r_t, lambda_=self.lambda_)

                    # Make sure it is the right type of data
                    alpha_rx = np.array(alpha_rx, np.csingle)
                    alpha_tx = np.array(alpha_tx, np.csingle)
                    beta = np.array(beta, np.csingle)

                    # Add another dimision with size 1 to be able to do a dot product between them when using Numba
                    alpha_rx = alpha_rx.reshape((len(alpha_rx), 1, self.Nr))
                    alpha_tx = alpha_tx.reshape((len(alpha_tx), 1, self.Nt))

                    # Calculate channel matrix H
                    H = helpers.jit_H(beta, alpha_rx, alpha_tx, self.Nr, self.Nt)

                    # Make sure it is the right type of data
                    self.W = np.array(self.W, np.csingle)
                    self.F = np.array(self.F, np.csingle)
                    H = np.array(H, np.csingle)

                    # Calculate the reward
                    R_tmp[b] = helpers.jit_Reward(H, self.F, self.W, self.P_t)
                R[path, step] = R_tmp.flatten()

        self.Reward_matrix = R

    def _get_reward(self, action):

        R = self.Reward_matrix[self.path, self.stepstart + self.stepnr]

        return R[action], np.max(R), np.min(R), np.mean(R)

    def _start_state(self):

        # Select a random start state - Actions
        self.state = np.random.choice(range(self.action_space_n), size=self.n_earlier_actions)

        # Add ori to the start state
        self.state = np.append(self.state, [self.ori[0] + np.zeros(self.n_earlier_ori)])

        # Add start postion to the start state + 'x' earlier posistions
        # x:
        self.state = np.append(self.state, [self.pos[0, 0] + np.zeros(self.n_earlier_pos)])

        # y:
        self.state = np.append(self.state, [self.pos[1, 0] + np.zeros(self.n_earlier_pos)])

        return self.state

    def _state_update(self, action):

        # ACTION
        # Insert new action in the front of the array
        state_tmp = np.insert(self.state, 0, action)

        # Remove the fourth element (The oldest action)
        self.state = np.delete(state_tmp, self.n_earlier_actions)

        # ORITATION
        if self.n_earlier_ori > 0:
            # Insert new action in the front of the array
            state_tmp = np.insert(self.state, self.n_earlier_actions, self.ori[self.stepnr])

            # Remove the fourth element (The oldest action)
            self.state = np.delete(state_tmp, self.n_earlier_actions + self.n_earlier_ori)

        # POSISTION
        # x:
        # Insert new action in the front of the array
        state_tmp = np.insert(self.state, self.n_earlier_actions + self.n_earlier_ori, self.pos[0, self.stepnr])

        # Remove the fourth element (The oldest action)
        self.state = np.delete(state_tmp, self.n_earlier_actions + self.n_earlier_ori + self.n_earlier_pos)

        # y:
        # Insert new action in the front of the array
        state_tmp = np.insert(self.state, self.n_earlier_actions + self.n_earlier_ori + self.n_earlier_pos,
                              self.pos[1, self.stepnr])

        # Remove the fourth element (The oldest action)
        self.state = np.delete(state_tmp, self.n_earlier_actions + self.n_earlier_ori + 2*self.n_earlier_pos)

        return self.state

    def step(self, action):

        # Get the reward
        reward, max_r, min_r, mean_r = self._get_reward(action)

        # Update counter
        self.stepnr += 1

        # Get the next_state
        next_state = self._state_update(action)

        # See if episode is finished
        if self.stepnr == self.nstep - 1:
            done = True
        else:
            done = False

        return next_state, reward, done, max_r, min_r, mean_r

    def reset(self, data_idx, path_idx):
        # Reset step counter
        self.stepnr = 0

        # Save where the step start and which mobility pattern is chosen
        self.stepstart = data_idx
        self.path = path_idx

        # Get the chosen mobility pattern
        self.pos = self.pos_log[path_idx][0][:, data_idx:data_idx + self.nstep]
        self.ori = self.ori_log[path_idx][0][2, data_idx:data_idx + self.nstep]

        # Return the start state()
        return self._start_state()
