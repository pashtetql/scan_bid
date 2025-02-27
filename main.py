from agent import Agent
from utils import load_data, save_data
from config import Config

def main():

    agent = Agent(Config.AGENT_NAME)
    print(agent.greet())

    data = load_data()
    print(agent.process(data))
    
    save_data(data)

if __name__ == "__main__":
    main()