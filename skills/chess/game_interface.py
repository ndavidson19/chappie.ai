import os
import json
import random
import numpy as np
import pandas as pd
from copy import deepcopy
from datetime import datetime

from ai.bot import Agent
from tasks.games.chess.chess import Chess
from skills.chess.game_plumbing import Plumbing

class chess:
    """
    Reinforcement training for AI
    """
    def __init__(self, train = False):
        """
        Input: train - boolean representing if the game is being played in training mode or not
        Description: initalize chess game
        Output: None
        """
        self.train = train

    def legal_moves(self, chess_game):
        """
        Input: chess_game - object containing the current chess game
        Description: returns all legal moves
        Output: numpy array containing all legal moves
        """
        legal = np.zeros((8,8,8,8))
        for cur,moves in chess_game.possible_board_moves(capture=True).items():
            if len(moves) > 0 and ((cur[0].isupper() and chess_game.p_move == 1) or (cur[0].islower() and chess_game.p_move == -1)):
                cur_pos = chess_game.board_2_array(cur)
                for next in moves:
                    legal[cur_pos[1]][cur_pos[0]][next[1]][next[0]] = 1.
        return legal.flatten()

    def play_game(
        self,
        game_name,
        epoch,
        train = False,
        EPD = None,
        players = [
            'skills/chess/data/active_param.json',
            'human'
        ]
    ):
        """
        Input: game_name - string representing the game board name
               epoch - integer representing the current epoch
               white - string representing the file name for the white player (Default='model-active.pth.tar') [OPTIONAL]
               black - string representing the file name for the black player (Default='model-new.pth.tar') [OPTIONAL]
               search_amount - integer representing the amount of searches the ai's should perform (Default=50) [OPTIONAL]
               max_depth - integer representing the max depth each search can go (Default=5) [OPTIONAL]
               best_of - integer representing the amount of games played in a bracket (Default=5) [OPTIONAL]
        Description: Plays game for training
        Output: tuple containing game state, training data and which of the players won
        """
        log = []
        human_code = [
            'h',
            'hum',
            'human'
        ]
        end = False
        a_players = []
        plumbing = Plumbing()
        if EPD is None:
            chess_game = deepcopy(Chess()) #'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -'
        else:
            chess_game = deepcopy(Chess(EPD=EPD)) #'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -'
        while True:
            for i, p in enumerate(players):
                while True:
                    if str(p).lower() in human_code and len(log) < len(players):
                        a_players.append('human')
                    elif len(log) < len(players):
                        a_players.append(deepcopy(Agent(param_name = p, train = train)))
                    if 'human' in a_players:
                        if chess_game.p_move == 1:
                            print('\nWhites Turn [UPPER CASE]\n')
                        else:
                            print('\nBlacks Turn [LOWER CASE]\n')
                        chess_game.display()
                    enc_state = plumbing.encode_state(chess_game)
                    if a_players[i] == 'human':
                        cur = input('What piece do you want to move?\n')
                        next = input('Where do you want to move the piece to?\n')
                    else:
                        legal = self.legal_moves(chess_game) #Filter legal moves for inital state
                        legal[legal == 0] = float('-inf')
                        probs, v = a_players[i].choose_action(enc_state, legal_moves = legal)
                        max_prob = max(probs)
                        print(f'Value = {v}')
                        print(f'Move Probability = {max_prob}')
                        a_bank = [j for j, v in enumerate(probs) if v == max_prob]
                        b_a = random.choice(a_bank)
                        a_map = np.zeros(4096)
                        a_map[b_a] = 1
                        a_map = a_map.reshape((8,8,8,8))
                        a_index = [(cy, cx, ny, nx) for cy, cx, ny, nx in zip(*np.where(a_map == 1))][0]
                        cur = f'{chess_game.x[a_index[1]]}{chess_game.y[a_index[0]]}'
                        next = f'{chess_game.x[a_index[3]]}{chess_game.y[a_index[2]]}'

                    valid = False
                    if chess_game.move(cur,next) == False:
                        print('Invalid move')
                    else:
                        valid = True
                        log.append({
                            **{f'state{i}':float(s) for i,s in enumerate(plumbing.encode_state(chess_game)[0])},
                            **{f'prob{x}':p for x, p in enumerate(probs)}
                        })
                        if chess_game.p_move > 0:
                            print(f'w {cur.lower()}-->{next.lower()} | GAME:{epoch} BOARD:{game_name} MOVE:{len(log)} HASH:{chess_game.EPD_hash()}\n')  
                        else:
                            print(f'b {cur.lower()}-->{next.lower()} | GAME:{epoch} BOARD:{game_name} MOVE:{len(log)} HASH:{chess_game.EPD_hash()}\n')
                        if a_players[i] != 'human':
                            state = chess_game.check_state(chess_game.EPD_hash())
                            if state == '50M' or state == '3F':
                                state = [0,1,0] #Auto tie
                            elif state == 'PP':
                                chess_game.pawn_promotion(n_part='Q') #Auto queen
                            if state != [0,1,0]:
                                state = chess_game.is_end()
                        else:
                            state = chess_game.is_end()
                            if state == [0,0,0]:
                                if chess_game.check_state(chess_game.EPD_hash()) == 'PP':
                                    chess_game.pawn_promotion()
                        if sum(state) > 0:
                            print(f'FINISHED | GAME:{epoch} BOARD:{game_name} MOVE:{len(log)} STATE:{state}\n')
                            game_train_data = pd.DataFrame(log)
                            game_train_data = game_train_data.astype(float)
                            end = True
                        break
                if end == True:
                    break
                if valid == True:
                    chess_game.p_move = chess_game.p_move * (-1)
            if end == True:
                break
        del a_players
        return state, game_train_data

    def traing_session(
        self,
        games = 10,
        boards = 1,
        best_of = 5,
        EPD = None,
        players = [
            {
                'param':'skills/chess/data/active_param.json',
                'train':False
            },
            {
                'param':'skills/chess/data/new_param.json',
                'train':True
            }
        ]
    ):
        #Initalize variables
        GAMES = games #Games to play on each board
        BOARDS = boards #Amount of boards to play on at a time
        BEST_OF = best_of #Amount of games played when evaluating the models
        t_bank = []
        a_players = []
        game_results = {'white':0, 'black':0, 'tie':0}
        for p in players:
            a_players.append(p['param'])
            if p['train'] == True:
                t_bank.append(p['param'])
        train_data = pd.DataFrame()
        if os.path.exists('skills/chess/data/training_log.csv'):
            t_log = pd.read_csv('skills/chess/data/training_log.csv')
        else:
            t_log = pd.DataFrame()
        #Begin training games
        for epoch in range(GAMES):
            print(f'STARTING GAMES\n')
            state, train_data = self.play_game(
                'TEST',
                epoch,
                train = True,
                EPD = EPD,
                players = a_players
            )
            if state == [1,0,0]:
                print(f'WHITE WINS')
                game_results['white'] += 1
            elif state == [0,0,1]:
                print(f'BLACK WINS')
                game_results['black'] += 1
            else:
                print('TIE GAME')
                game_results['tie'] += 1
            print(game_results)
            print()
            if sum([v for v in game_results.values()]) >= BEST_OF:
                game_results = {p: 0 for p in a_players}
            if state == [0,0,0]:
                train_data['value'] = [0.] * len(train_data)
            elif state == [1,0,0]:
                train_data['value'] = np.where(train_data['state0'] == 0., 1., -1.)
            else:
                train_data['value'] = np.where(train_data['state0'] == 0., -1., 1.)
            train_data['reward'] = [0.] * len(train_data)
            for m in t_bank:
                m_log = pd.DataFrame(Agent(param_name = m, train = False).train(train_data))
                m_log['model'] = m
                t_log = t_log.append(m_log,ignore_index=True)
                del m_log
            t_log.to_csv('skills/chess/data/training_log.csv', index=False)
            if os.path.exists('skills/chess/data/game_log.csv'):
                g_log = pd.read_csv('skills/chess/data/game_log.csv')
            else:
                g_log = pd.DataFrame()
            train_data['Date'] = [datetime.now()] * len(train_data)
            g_log = g_log.append(train_data, ignore_index=True)
            g_log.to_csv('skills/chess/data/game_log.csv', index=False)
            del g_log
            train_data = pd.DataFrame()
            a_players.reverse()
