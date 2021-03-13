# -*- coding: utf-8 -*-
import random
import numpy as np
from scipy.stats import norm

class GameState:
    """
    Class to hold game state for each eval/game.
    """

    # Game states
    UNBLOCKED = 0
    BLOCKED = 1
    ATTACKER_DETECTED = 2


    def __init__(self):
        """
        Set up the game state given initialization parameters as listed.
        """

        self.time_limit = 100
        self.t = 0

        # Attacker score is amount of observation by the attacker (omega in Sartias paper)
        self.attacker_score = 0

        self.defender_score = 0


        self.state = GameState.UNBLOCKED

        # maintain the amount of traffic generated by the user each turn
        self.user_history = []
        # maintain user behavior values (only relevant when traffic is generated)
        self.behavior_history = [] # see COMMENTARY tag in controllers.py
        # behavior_mask is 1 for turn t if A(t) > 0, and 0 otherwise
        self.behavior_mask = []
        # listening mask is 1 if the attacker is listening at turn t
        self.listening_mask = []
        

        self.rng = np.default_rng()


        # User traffic: arrivals modeled by Poisson process with
        # intensity lambda_u/iota where iota = length of time slot
        self.lambda_u = 1
        # fun fact: a branching process where the number of branches at each
        # node is determined by a poisson process with lambda <= 1 dies out
        # almost surely

        # User behavior
        # Gaussian distribution with mean 100 and variance 3
        self.beta_u = 100
        self.sigma_u = 3

        # False Positive (FP) rate
        self.eta_u = 0.01

        # User reward in Unblocked state
        self.nu_r = 0.1

        # Cut-off point for detecting attack: if Beta_u > c then positive
        # (assuming being attacked); false positives possible
        # the cut off is the point at which the area under the normal curve to
        # the right of the cut off is equal to the false positive rate
        self.c_r = norm.ppf(1 - self.eta_u)

        # Probability of IDS detecting attacker listening (function of m)
        # Assume: concave function, delta(0) = 0 and delta(m->inf) = 1
        self.delta_l = 0.1

        # Probability of IDS detecting attacker attacking (function of m)
        # Assume: concave function, delta(0) = 0 and delta(m->inf) = 1
        self.delta_a = 0.2

        # Probability that user blocked in time state t is unblocked in t+1
        self.q = 0.7

        # # Discount factor ????
        # self.rho = 0.98
        # I'm not sure if the discount factor applies outside of value iteration
        # (it's used to derive attacker reward, which is explicit in
        # reinforcement learning and implicit in evolutionary computing? Fact
        # check me on that)

        # Attacker learning rate
        self.gamma = 0.1

        # Per-time-slot cost of operating IDS
        self.m = 0

        # Attacker's cost of compromising system
        self.C_a = 0


    def T(self):
        """
        Return current time step in simulation
        """
        return self.t


    def S(self):
        """
        Return state (blocked or unblocked)
        """
        return self.state


    def W(self):
        """
        Return amount of observation by the attacker
        """
        return self.attacker_score


    def play_turn(self, world_data, attacker_controllers, defender_controllers):
        """
        Play a turn of a game given world_data to log world updates
        and controllers for Attacker and Defenders.

        During a turn, the following takes place (somewhat sequentially):
        
        The attacker decides whether to wait, listen, or attack given the
        current game state and the amount of prior traffic seen

        If the game state is non-blocking:
        The user generates 0 or more traffic according to a poisson distribution
        with mean lambda.

        TODO: find out whether the following is consistent with the paper. We
        will probably end up modifying it a bit anyways.

        If the game state is non-blocking:
        If the attacker generates traffic:
        The defender decides whether to block based on traffic generated by the
        attacker
        If the attacker does not generate traffic and the user generates
        traffic:
        The defender decides whether to block based on traffic generated by the
        user
        
        :ODOT
        
        IDS checks are performed based on the attacker's actions and the game
        state may transition to attacker detected and game_over

        The game state may transition to blocked depending on the actions of the
        defender

        The game state may transition to unblocked depending on if the game was
        blocked during the current turn
        """
        game_over = False

        self.t += 1

        # Assume one attacker and one defender
        attacker = attacker_controllers[0]
        defender = defender_controllers[0]
        # NOTE multi-user / attacker situations might be easy to extend
        
        # The attacker starts first
        attacker.decide_move(self)
        self.listening_mask.append(attacker.next_move == 'listen')
        
        # Then the user generates traffic if the game state allows
        if (self.state == GameState.UNBLOCKED):
            self.user_history.append(np.random.poisson(self.lambda_u))
        else:
            self.user_history.append(0)

        # If the attacker decides to attack, the traffic generated by the
        # attacker currently subsumes any traffic generated by the user in the
        # defender's decision (see TODO in docstring above)
        if (attacker.next_move == 'attack' and
            self.state == GameState.UNBLOCKED):
            L_t = np.array(self.user_history)[np.array(self.listening_mask)]
            self.behavior_history.append(np.random.normal(
                self.beta_u * (1 + math.exp(-self.gamma * np.sum(L_t))),
                self.sigma_u * (1 + math.exp(-self.gamma * np.sum(L_t)))))
            self.behavior_mask.append(True)
        elif (self.user_history[-1]):
            # if the user generates any traffic, that behavior is N(beta_u, sigma_u)
            self.behavior_history.append(np.random.normal(self.beta_u,
                                                          self.sigma_u))
            self.behavior_mask.append(True)
        else:
            self.behavior_history.append(0)
            self.behavior_mask.append(False)
        
        defender.decide_move(self)

        world_data.append('attacker: ' + attacker.next_move + ' vs. defender: '
                          + defender.next_move + '\n')

        # transition to blocked if the defender decides to block
        if (self.state == GameState.UNBLOCKED and defender.next_move == 'block'):
            self.state = GameState.BLOCKED
        elif (self.state == GameState.BLOCKED):
            # remain blocked with probability q
            self.state = (GameState.UNBLOCKED, GameState.BLOCKED)[np.random.uniform(0,1) < self.q]
        # else remain unblocked
        
        if (attacker.next_move == 'listen'):
            if (random.random() < self.delta_l):
                self.state = GameState.ATTACKER_DETECTED
        elif (attacker.next_move == 'attack'):
            if (random.random() < self.delta_a):
                self.state = GameState.ATTACKER_DETECTED
            else:
                self.attacker_score += self.c_r
                self.defender_score -= self.c_r

        # If attacker is detected, game over
        if ((self.state == GameState.ATTACKER_DETECTED)
            or ((self.time_limit - self.t) == 0)):
            game_over = True

        return game_over



"""

Saritas:

User behvaior:
t = time slot
u = user
r = resource
Lambda_u(t) = amount of traffic generated by user u in time slot t
(Poisson distributed with parameter lambda_u)
--> arrivals modeled by Poisson process with intensity lambda_u/iota where
iota = length of time slot)

m = per-time-slot cost of operating IDS
user behavior described by Gaussian distribution Beta_u ~ Nu(beta_u, sigma_u)
  with mean beta_u and variance sigma_u

user behavior is verified at end of every time slot; decision is made based
  on match of user behavior model and actual behavior during slot.

c = cut-off point
if Beta_user > c then positive (assuming being attacked); false positives possible
eta_u = false positive (FP) rate
system applies detection threshold of c = Phi_u^-1 (1 - eta_u) where
  Phi_u is cumulative dsitribution function (CDF) of Beta_u

S = system, which is in one of three states: BL, UB, or AD (blocked, unblocked, attacker detected)
In state UB, user can generate reward nu_r
If user fails CA (either FP or true positive (TP)), system changes from UB to BL

q = probability that user blocked in time state t is unblocked in t+1

L(t) = number of observations by attacker at time t

At time t:
    l(t) = 1, a(t) = 0 if listening



"""
