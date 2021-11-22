import math
import torch
import random
from copy import deepcopy
from numpy.random import dirichlet

class MCTS:
    """
    Monte Carlo Tree Search algorithm used to search game tree for the best move
    """
    def __init__(
        self,
        dynamics,
        value,
        policy,
        state,
        reward,
        user = None,
        c1 = 1.25,
        c2 = 19652,
        d_a = .3,
        e_f = .25,
        g_d = 1.,
        single_player = False,
        max_depth = float('inf')
    ):
        """
        Input: prediction - NN used to predict p, v values
               dynamics - NN used to predict the next states hidden values and the reward
               user - integer representing which user the agent is (default = None) [OPTIONAL]
               c1 - float representing a search hyperparameter (default = 1.25) [OPTIONAL]
               c2 - float representing a search hyperparameter (default = 19652) [OPTIONAL]
               d_a = float representing the dirichlet alpha you wish to use (default = 0.3) [OPTIONAL]
               e_f = float representing the exploration fraction you wish to use with dirichlet alpha noise (default = 0.25) [OPTIONAL]
               g_d = float representing the gamma discount to apply to v_k+1 when backpropagating tree (default = 1) [OPTIONAL]
               max_depth - integer representing the max allowable depth to search tree (default = inf) [OPTIONAL]
        Description: MCTS initail variables
        Output: None
        """
        self.tree = {} #Game tree
        self.l = 0 #Last node depth
        self.v_l = 0 #Last node value
        self.max_depth = max_depth #Max allowable depth
        self.c1 = c1 #Exploration hyper parameter 1
        self.c2 = c2 #Exploration hyper parameter 2
        self.d_a = d_a #Dirichlet alpha
        self.e_f = e_f #Exploration fraction
        self.g_d = g_d #Gamma discount
        self.Q_max = 1 #Max value
        self.Q_min = -1 #Min value
        self.g = dynamics #Model used for dynamics
        self.v = value #Model used for value
        self.p = policy #Model used for policy
        self.s = state #Model used for state
        self.r = reward #Model used for reward
        self.single_player = single_player #Control for if the task is single player or not

    class Node:
        """
        Node for each state in the game tree
        """
        def __init__(self):
            """
            Input: None
            Description: Node initail variables
            Output: None
            """
            self.N = 0 #Visits
            self.Q = 0 #Value
            self.R = 0 #Reward
            self.S = None #State
            self.P = None #Policy

    def state_hash(self, s):
        """
        Input: s - tensor representing hidden state of task
        Description: generate unique hash of the supplied hidden state
        Output: integer representing unique hash of the supplied hidden state
        """
        result = hash(str(s))
        return result

    def dirichlet_noise(self, p):
        """
        Input: p - list of floats [0-1] representing action probability distrabution
        Description: add dirichlet noise to probability distrabution
        Output: list of floats [0-1] representing action probability with added noise
        """
        d = dirichlet([self.d_a] * len(p))
        return torch.tensor(d * self.e_f) + (torch.matmul(torch.tensor([1 - self.e_f]), p))

    def pUCT(self, s):
        """
        Input: s - tensor representing hidden state of task
        Description: return best action state using polynomial upper confidence trees
        Output: list containing pUCT values for all acitons
        """
        p_visits = sum([self.tree[(s, b)].N for b in range(self.p.action_space)]) #Sum of all potential nodes

        u_bank = {}
        for a in range(self.p.action_space):
            U = self.tree[(s, a)].P * ((p_visits**(0.5))/(1+self.tree[(s, a)].N)) #First part of exploration
            U *= self.c1 + (math.log((p_visits + (self.p.action_space * self.c2) + self.p.action_space) / self.c2)) #Second part of exploration
            Q_n = (self.tree[(s, a)].Q - self.Q_min) / (self.Q_max - self.Q_min) #Normalized value
            u_bank[a] = Q_n + U
        m_u = max(u_bank.values())
        a_bank = [k for k,v in u_bank.items() if v == m_u]
        return random.choice(a_bank)

    def search(self, s, a = None, train = False):
        """
        Input: s - tensor representing hidden state of task
               a - integer representing which action is being performed (default = None) [OPTIONAL]
               train - boolean representing if search is being used in training mode (default = False) [OPTIONAL]
        Description: Search the task action tree using upper confidence value
        Output: predicted value
        """
        if a is not None:
            a_hash = deepcopy(a.reshape(1).item())
        else:
            a_hash = None
        s_hash = self.state_hash(s) #Create hash of state [sk-1] for game tree
        if (s_hash, a_hash) not in self.tree:
            self.tree[(s_hash, a_hash)] = self.Node() #Initialize new game tree node
        if a is not None and self.tree[(s_hash, a_hash)].S is None:
            with torch.no_grad():
                d_k = self.g(s, a + 1) #dynamics function
                #print('d',d_k.size())
                r_k = self.r(d_k) #reward function
                s_k = self.s(d_k) #next state function
                #print('s',s_k.size())
            s = s_k.reshape(s.size())
            self.tree[(s_hash, a_hash)].S = s
            self.tree[(s_hash, a_hash)].R = r_k.reshape(1).item()
        elif a is not None and self.tree[(s_hash, a_hash)].S is not None:
            d = self.tree[(s_hash, a_hash)].S
        sk_hash = self.state_hash(s) #Create hash of state [sk] for game tree
        if self.tree[(s_hash, a_hash)].N == 0:
            #EXPANSION ---
            with torch.no_grad():
                v_k = self.v(s) #value function
                p = self.p(s) #policy function
            if a is None and train is True:
                p = self.dirichlet_noise(p) #Add dirichlet noise to p @ s0
            self.tree[(s_hash, a_hash)].Q = v_k.reshape(1).item()
            self.v_l = self.tree[(s_hash, a_hash)].Q
            for a_k, p_a in enumerate(p.reshape(self.p.action_space)):
                if (sk_hash, a_k) not in self.tree:
                    self.tree[(sk_hash, a_k)] = self.Node()
                self.tree[(sk_hash, a_k)].P = p_a.item()
        elif self.l < self.max_depth:
            a_k = torch.tensor(self.pUCT(sk_hash)) #Find best action to perform @ [sk]
            a_k = a_k.reshape((1,1))
            k = self.l
            self.l += 1
            #BACKUP ---
            G_1, r_1 = self.search(s, a_k) #Go level deeper
            if (self.l - k - 1) > 0:
                G_k = ((self.g_d ** (self.l - k - 1)) * r_1) + ((self.g_d ** (self.l - k)) * self.v_l)
                G = G_1 + G_k
            else:
                G = 0
            self.tree[(s_hash, a_hash)].Q = ((self.tree[(s_hash, a_hash)].N * self.tree[(s_hash, a_hash)].Q) + G) / (self.tree[(s_hash, a_hash)].N + 1) #Updated value
        if self.tree[(s_hash, a_hash)].Q < self.Q_min:
            self.Q_min = self.tree[(s_hash, a_hash)].Q
        if self.tree[(s_hash, a_hash)].Q > self.Q_max:
            self.Q_max = self.tree[(s_hash, a_hash)].Q
        self.tree[(s_hash, a_hash)].N += 1
        if 'G' not in locals():
            G = 0
        if self.single_player == True:
            return G, self.tree[(s_hash, a_hash)].R
        else:
            return G, -self.tree[(s_hash, a_hash)].R
