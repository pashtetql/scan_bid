import logging
import os.path
import random
import time

from fake_useragent import UserAgent
from requests import post, get

from GameInfo import GameInfo
from AccessInfo import AccessInfo
from endpoints import GAME_URL, CLAIM_GAME_URL, REFRESH_URL, CLAIM_BLUM_URL, START_FARMING_URL, BALANCE_URL, \
    DAILY_REWARD_URL, CLAIM_FRIENDS_BLUM_URL


class GamePlayer:
    def __init__(
            self,
            min_game_points: int,
            max_game_points: int,
            request_wait_time: int,
            users_file: str = 'credentials.txt',
            proxies_file: str = 'proxies.txt',
            debug_mode: bool = False,
            main_log_file: str = 'logs/info.log',
            critical_log_file: str = 'logs/critical.log',
            balance_log_file: str = 'logs/balance.log'
    ):
        self.username_to_info: dict[str, AccessInfo] = {}
        self.invalid_users_info: dict[str, AccessInfo] = {}
        self.users_file = users_file
        self.proxies_file = proxies_file
        self.user_agent_rotator = UserAgent()
        self.debug_mode = debug_mode
        self.min_game_points = min_game_points
        self.max_game_points = max_game_points
        self.request_wait_time = request_wait_time
        self.critical_file_name = critical_log_file
        self.balance_log_file = balance_log_file

        os.makedirs(os.path.dirname(main_log_file), exist_ok=True)
        os.makedirs(os.path.dirname(critical_log_file), exist_ok=True)
        os.makedirs(os.path.dirname(balance_log_file), exist_ok=True)

        if debug_mode:
            logging.basicConfig(
                level=logging.INFO,
                filename=main_log_file,
                format='%(asctime)s (%(message)s)',
                datefmt='%d.%m.%Y %H:%M:%S',
                filemode='w'
            )

            logging.info("logger initialized")

    def read_accounts_from_file(self) -> bool:
        if not os.path.isfile(self.users_file):
            logging.info("read_accounts_from_file: file not exists")
            return False

        with open(self.users_file) as f:
            lines = f.readlines()

        for line in lines:
            try:
                username, token = line.split()
                self.username_to_info[username] = AccessInfo(
                    access=None,
                    refresh=token,
                    proxies=None,
                    last_access_update=None,
                    last_refresh_update=None
                )
            except ValueError:
                logging.info("read_accounts_from_file: wrong file format!")
                return False

        logging.info("read_accounts_from_file: successfully read accounts from file")
        return True

    def read_proxies_from_file(self) -> bool:
        if not os.path.isfile(self.proxies_file):
            logging.info("read_proxies_from_file: no proxies file")
            return True

        with open(self.proxies_file) as f:
            lines = f.readlines()

        for line in lines:
            try:
                username, http, https = line.split()
                if username not in self.username_to_info:
                    logging.info(f"read_proxies_from_file: usernames mismatch(not found {username})")
                    return False

                prev_info = self.username_to_info[username]
                self.username_to_info[username] = AccessInfo(
                    access=prev_info.access_token,
                    refresh=prev_info.refresh_token,
                    last_access_update=prev_info.last_access_update,
                    last_refresh_update=prev_info.last_refresh_update,
                    proxies={
                        'http': http,
                        'https': https
                    }
                )
            except ValueError:
                logging.info("read_proxies_from_file: wrong file format!")
                return False

        logging.info("read_proxies_from_file: successfully read proxies")
        return True

    def play_games(self):
        self.__refresh_tokens()

        username_to_game: dict[str, GameInfo] = {}
        for username in self.username_to_info:
            username_to_game[username] = GameInfo(None, None)

        logging.info(f"play_games: initially {len(username_to_game)} accounts")
        while len(username_to_game) > 0:
            to_delete = []

            for username in self.username_to_info:
                if username not in username_to_game:
                    continue

                try:
                    request = post(
                        url=GAME_URL,
                        headers={
                            "Authorization": f"Bearer {self.username_to_info[username].access_token}",
                            'User-Agent': self.user_agent_rotator.random
                        },
                        timeout=self.request_wait_time,
                        proxies=self.username_to_info[username].proxies
                    )
                except Exception as e:
                    logging.info(f"play_games: while playing for user {username}: {e}")
                    to_delete.append(username)
                    continue

                if request.status_code != 200:
                    logging.info(f"play_games: played all games for user {username}: {request.text}")
                    to_delete.append(username)
                    continue

                game_id = request.json()['gameId']
                username_to_game[username] = GameInfo(
                    game_id=game_id,
                    wait_time=time.time() + random.randint(30, 60)
                )

            for username in to_delete:
                username_to_game.pop(username)

            awaited_accounts = 0
            target_accounts = len(username_to_game)
            awaited_usernames = set()
            while awaited_accounts != target_accounts:
                for username, info in username_to_game.items():
                    if username not in awaited_usernames and time.time() > info.wait_time:
                        points = random.randint(self.min_game_points, self.max_game_points)

                        try:
                            request = post(
                                url=CLAIM_GAME_URL,
                                headers={
                                    'Authorization': f"Bearer {self.username_to_info[username].access_token}",
                                    'User-Agent': self.user_agent_rotator.random
                                },
                                json={
                                    'gameId': info.game_id,
                                    'points': points
                                },
                                proxies=self.username_to_info[username].proxies,
                                timeout=self.request_wait_time
                            )
                        except Exception as e:
                            logging.info(f"play_games: while claiming for user {username}: {e}")
                            awaited_accounts += 1
                            awaited_usernames.add(username)
                            continue

                        if request.status_code != 200:
                            logging.info(f"play_games: claim error for user {username}: {request.text}")
                        else:
                            logging.info(f"play_games: rewarded user {username} with {points}")

                        awaited_accounts += 1
                        awaited_usernames.add(username)

        logging.info("play_games: played all possible games for now")

    def __refresh_tokens(self, with_dump=True, dump_file='credentials.txt'):
        invalid_users = []
        expired_users = []
        new_tokens: dict[str, AccessInfo] = {}

        current_seconds = int(time.time())
        for username, info in (self.username_to_info | self.invalid_users_info).items():
            if info.token_is_up_to_date(current_seconds) and username in self.username_to_info:
                logging.info(f"refresh_tokens: token of {username} is up-to-date")
                continue

            try:
                request = post(
                    url=REFRESH_URL,
                    json={'refresh': info.refresh_token},
                    headers={'User-Agent': self.user_agent_rotator.random},
                    proxies=self.username_to_info[username].proxies,
                    timeout=self.request_wait_time
                )
            except Exception as e:
                logging.info(f"refresh_tokens: while refreshing token of {username}: {e}, token is marked as invalid")
                if username in self.username_to_info:
                    invalid_users.append(username)
                continue

            if request.status_code != 200:
                logging.info(f"refresh_tokens: "
                             f"token of {username} is expired and should be refreshed manually({request.text})")
                expired_users.append(username)
                if username in self.username_to_info:
                    invalid_users.append(username)
            else:
                data = request.json()
                new_tokens[username] = AccessInfo(
                    access=data['access'],
                    refresh=data['refresh'],
                    proxies=info.proxies,
                    last_access_update=current_seconds,
                    last_refresh_update=current_seconds
                )

        for username in invalid_users:
            self.invalid_users_info[username] = self.username_to_info.pop(username)

        for username, info in new_tokens.items():
            self.username_to_info[username] = info

        if len(expired_users) > 0:
            with open(self.critical_file_name, 'w') as f:
                for username in expired_users:
                    f.write(f"token of {username} should be refreshed manually\n")
        else:  # silent remove
            try:
                os.remove(self.critical_file_name)
            except OSError:
                pass

        if with_dump:
            with open(file=dump_file, mode='w') as f:
                for username, info in (self.username_to_info | self.invalid_users_info).items():
                    f.write(f"{username} {info.refresh_token}\n")

        logging.info(f"refresh_tokens: {len(self.username_to_info)} users are now processing")
        logging.info(f"refresh_tokens: {len(self.invalid_users_info)} users are now invalid")
        logging.info(f"refresh_tokens: {len(expired_users)} users are now expired")

    def collect_blum(self):
        self.__refresh_tokens()

        logging.info("collect_blum: started collecting blum")
        for username, info in self.username_to_info.items():
            try:
                response = post(
                    url=CLAIM_BLUM_URL,
                    headers={
                        'Authorization': f"Bearer {info.access_token}",
                        'User-Agent': self.user_agent_rotator.random
                    },
                    proxies=self.username_to_info[username].proxies,
                    timeout=self.request_wait_time
                )
            except Exception as e:
                logging.info(f"collect_blum: while collecting blum for {username}: {e}")
                continue

            if response.status_code != 200:
                logging.info(f"collect_blum: couldn't collect blum for {username}: {response.text}")
            else:
                logging.info(f"collect_blum: collected blum for {username}")

            try:
                response = post(
                    url=START_FARMING_URL,
                    headers={
                        'Authorization': f"Bearer {info.access_token}",
                        'User-Agent': self.user_agent_rotator.random
                    },
                    proxies=self.username_to_info[username].proxies,
                    timeout=self.request_wait_time
                )
            except Exception as e:
                logging.info(f"collect_blum: while starting to farm blum for {username}: {e}")
                continue

            if response.status_code == 200:
                logging.info(f"collect_blum: started farming for {username}")
            else:
                logging.info(f"collect_blum: couldn't start farming for {username}: {response.text}")

        logging.info("collect_blum: finished collecting blum")

    def count_total_money(self):
        if not self.debug_mode:
            return

        self.__refresh_tokens()
        logging.info("count_total_money: started counting money")

        with open(self.balance_log_file, 'w') as f:
            total_money = 0
            for username, info in self.username_to_info.items():
                try:
                    response = get(
                        url=BALANCE_URL,
                        headers={
                            'Authorization': f"Bearer {info.access_token}",
                            'User-Agent': self.user_agent_rotator.random
                        },
                        proxies=self.username_to_info[username].proxies,
                        timeout=self.request_wait_time
                    )
                except Exception as e:
                    logging.info(f"count_total_money: while claiming money for user {username}: {e}")
                    continue

                if response.status_code != 200:
                    logging.info(f"count_total_money: "
                                 f"something went wrong while claiming money for user {username}: {response.text}")
                    continue

                user_money = float(response.json()['availableBalance'])
                f.write(f"{username}: {user_money}\n")
                total_money += user_money

            f.write(f"total active accounts: {len(self.username_to_info)}\n")
            f.write("total blum points: {:.2f}\n".format(total_money))

        logging.info("count_total_money: finished counting money")

    def collect_daily_rewards(self):
        self.__refresh_tokens()

        logging.info("collect_daily_rewards: started collecting daily rewards")
        for username, info in self.username_to_info.items():
            try:
                response = post(
                    url=DAILY_REWARD_URL,
                    headers={
                        'Authorization': f"Bearer {info.access_token}",
                        'User-Agent': self.user_agent_rotator.random
                    },
                    proxies=self.username_to_info[username].proxies,
                    timeout=self.request_wait_time
                )
            except Exception as e:
                logging.info(f"collect_daily_rewards: while getting daily rewards for user {username}: {e}")
                continue

            if self.debug_mode:
                if response.status_code == 200:
                    logging.info(f"collect_daily_rewards: collected daily rewards for user {username}")
                else:
                    logging.info(f"collect_daily_rewards: "
                                 f"cannot get daily rewards for user {username}: {response.text}")

        logging.info("collect_daily_rewards: finished collecting daily rewards")

    def collect_friends_blum(self):
        self.__refresh_tokens()

        logging.info("collect_friends_blum: started collecting friends' blum")
        for username, info in self.username_to_info.items():
            try:
                response = post(
                    url=CLAIM_FRIENDS_BLUM_URL,
                    headers={
                        'Authorization': f"Bearer {info.access_token}",
                        'User-Agent': self.user_agent_rotator.random
                    },
                    proxies=self.username_to_info[username].proxies,
                    timeout=self.request_wait_time
                )
            except Exception as e:
                logging.info(f"collect_friends_blum: while getting blum for inviting friends for user {username}: {e}")
                continue

            if response.status_code != 200:
                if self.debug_mode:
                    logging.info(f"collect_friends_blum: "
                                 f"cannot get blum for inviting friends for user {username}: {response.text}")
                continue

            if self.debug_mode:
                logging.info(f"collect_friends_blum: collected blum for inviting friends for user {username}")

        logging.info("collect_friends_blum: finished collecting friends' blum")
