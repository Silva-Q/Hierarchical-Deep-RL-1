import random
from collections import deque

import gym

import torch
from torch.autograd import Variable
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim


env = gym.make('SpaceInvaders-v0')
env.render()

alpha, gamma, epsilon, N = (0.65, 0.65, 0.925, 6)


def wrape_state(state):
    return Variable(torch.Tensor(state).view(3, 210, 160).unsqueeze(0))


class DQN(nn.Module):
    """A NN from state to actions."""
    def __init__(self, num_actions, g_size, ram_size):
        super(DQN, self).__init__()
        self.g_size = g_size
        self.num_actions = num_actions

        self.conv1 = nn.Conv2d(3, 32, kernel_size=8, stride=4)
        self.conv2 = nn.Conv2d(32, 64, kernel_size=4, stride=2)
        self.conv3 = nn.Conv2d(64, 64, kernel_size=3, stride=1)
        # self.fc4 = nn.Linear(22528, 256)
        # self.fc5 = nn.Linear(256 + g_size, num_actions)
        # self.tanh = nn.Tanh()
        self.softmax = nn.Softmax()
        self.lstm_hidden = (Variable(torch.rand(3, 1, self.num_actions)),
                            Variable(torch.rand(3, 1, self.num_actions)))
        self.lstm = nn.LSTM(22528 + self.g_size, self.num_actions, 3)

        self.optimizer = optim.Adam(self.parameters(), lr=alpha)
        self.criterion = nn.MSELoss()

        t = (wrape_state(env.reset()), 0)
        self.D = deque(ram_size * [(t, 0, t)], ram_size)

    def forward(self, x, g):
        x = F.relu(self.conv1(x))
        x = F.relu(self.conv2(x))
        x = self.softmax(self.conv3(x))
        # x = self.fc4(x.view(x.size(0), -1))
        # x = self.tanh(x)

        g_list = [-0.5 for i in range(self.g_size)]
        g_list[g] = 1.0
        g_list = Variable(torch.Tensor([g_list]))
        x = torch.cat((g_list, x.view(1, -1)), 1)

        y, self.lstm_hidden = self.lstm(x.view(1, 1, -1), self.lstm_hidden)
        self.lstm_hidden = (Variable(self.lstm_hidden[0].data),
                            Variable(self.lstm_hidden[1].data))
        # return self.fc5(torch.cat((x, g_list), 1))
        return y.view(1, self.num_actions)

    def epsilon_greedy(self, state, g):
        action = 0
        if torch.rand(1)[0] > epsilon:
            action = env.action_space.sample()
        else:
            Q = self(state, g)
            action = Q.data.max(1)[1]
        return action


class MetaController(nn.Module):
    """Meta-controller that gives policy for critic."""
    def __init__(self, g_size, ram_size):
        super(MetaController, self).__init__()
        self.g_size = g_size

        self.conv1 = nn.Conv2d(3, 16, kernel_size=8, stride=4)
        self.conv2 = nn.Conv2d(16, 16, kernel_size=4)
        # self.fc1 = nn.Linear(27648, self.g_size)
        # elf.tanh = nn.Tanh()
        self.lstm_hidden = (Variable(torch.rand(2, 1, self.g_size)),
                            Variable(torch.rand(2, 1, self.g_size)))
        self.lstm = nn.LSTM(27648, self.g_size, 2)

        self.optimizer = optim.Adam(self.parameters(), lr=alpha)
        self.criterion = nn.MSELoss()

        t = wrape_state(env.reset())
        self.D = deque(ram_size * [(t, 0, t)], ram_size)

    def forward(self, x):
        x = F.relu(self.conv1(x))
        x = F.relu(self.conv2(x))
        # return self.tanh(self.fc1(x.view(x.size(0), -1)))
        y, self.lstm_hidden = self.lstm(x.view(1, 1, -1), self.lstm_hidden)
        self.lstm_hidden = (Variable(self.lstm_hidden[0].data),
                            Variable(self.lstm_hidden[1].data))
        return y.view(1, self.g_size)

    def epsilon_greedy(self, state):
        g = 0
        if torch.rand(1)[0] > epsilon:
            g = random.sample(range(self.g_size), 1)
            g = g[0]
        else:
            Q = self(state)
            g = Q.data.max(1)[1][0]
        return g


class Agent:
    """Hierarchical DQN agent."""
    def __init__(self, num_actions, g_size, ram_size):
        self.num_actions = num_actions
        self.g_size = g_size

        self.meta_controller = MetaController(self.g_size, ram_size)
        self.critic = DQN(num_actions, self.g_size, ram_size)

    def update(self):
        self.optimize(self.critic, 6, self.num_actions)
        self.optimize(self.meta_controller, 4, self.g_size)

    def optimize(self, model, batch_size, out_num):
        batch = random.sample(model.D, batch_size)
        for sample in batch:
            state1, reward, state2 = sample

            Q2, Q1 = (0, 0)
            if len(state2) == 1:
                Q2 = model(state2).data.max(1)[0]
                Q1 = Variable(model(state1).data, volatile=True)
            else:
                Q2 = model(*state2).data.max(1)[0]
                Q1 = Variable(model(*state1).data, volatile=True)
            Q2 = reward + gamma * Variable(Q2, requires_grad=True)
            Q2 = torch.cat([Q2 for i in range(out_num)])

            model.optimizer.zero_grad()
            loss = model.criterion(Q2, Q1)
            loss.backward()
            model.optimizer.step()


agent = Agent(env.action_space.n, 6, 16)

for episode in range(1, 201):
    done = False
    G = 0

    state0 = wrape_state(env.reset())
    state1 = state0

    g = agent.meta_controller.epsilon_greedy(state1)
    while done is not True:
        extrinsic_reward = 0
        n = 0

        while not done and n < N:
            action = agent.critic.epsilon_greedy(state1, g)
            state2, f, done, info = env.step(action)

            state2 = wrape_state(state2)
            agent.critic.D.append(((state1, g), f, (state2, g)))

            agent.update()

            extrinsic_reward += f
            state1 = state2

            n += 1

            G += f
            env.render()
        agent.meta_controller.D.append((state0, extrinsic_reward, state1))
        if not done:
            g = agent.meta_controller.epsilon_greedy(state1)

    if episode % 50 == 0:
        print("Episode {}: Total reward = {}.".format(episode, G))
