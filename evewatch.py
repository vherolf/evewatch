from datetime import datetime
from pathlib import Path
import asyncio, aiofiles
import time
import re
from dataclasses import dataclass
import asyncio_mqtt as aiomqtt
import paho.mqtt as mqtt
#import graphviz

#g = graphviz.Graph('G', filename='eve-universe.gv', engine='sfdp', strict=True)

start_logging = False
# changed the first time you jump to another system
current_solarsystem = ''

today = datetime.now()
chatlogdir = list(Path.home().rglob( 'EVE/logs/Chatlogs' )).pop()
# chat channel you wanna check
channellist = ['AKIMA WH','INTEL.RC','Local','Heavy Metal Pirates']
# check for mentions of this usernames
usernames = ['Vherolf']

# make the chatlognames from today with pathlib glob and the channellist
chats=[]
for channel in channellist:
    chats += list(chatlogdir.glob(channel+'_'+str(today.year) + str(today.month) + str(today.day)+'*'))

# solar systems that should be watched 
solarsystemlist = ['MVCJ-E','MVC','BK4-YC','2-TEGJ','LF-2KP','F-YH5B','K1I1-J','BK4','BK4-']



async def mqtttrigger(plug="plug3"):
    async with aiomqtt.Client(hostname="hass.lan",
                              username="mqttmqtt",
                              password="mqttmqtt") as client:
        await client.publish(f"eve/{plug}", payload=f"TOGGLE")

@dataclass(frozen=True, slots=True)
class Message:
    timestamp: datetime
    username: str
    message: str
    #message_hash: str

## this function is from https://github.com/andrewpmartinez/py-eve-chat-mon (THANK YOU!)
async def parse_msg(raw_msg):
    line_parser = re.compile('^\s*\[\s(.*?)\s\]\s(.*?)\s>\s(.*?)$', re.DOTALL)
    match = line_parser.match(raw_msg)
    if match:
        timestamp = match.group(1)
        username = match.group(2)
        message = match.group(3)
        timestamp = datetime.strptime(timestamp, "%Y.%m.%d %H:%M:%S")
        
        parsed_msg = Message(timestamp = timestamp,
                      username = username,
                      message = message)
        return parsed_msg

    return None

# # Filter: fires every time you pass a stargate and sets your current solar system
# async def system_locator_filter(parsed_msg):
#     global current_solarsystem
#     last_solarsystem = current_solarsystem
#     if parsed_msg['username'] == "EVE System":
#         system_change = parsed_msg['message'].find('Channel changed to Local :')
#         if system_change != '-1':
#             current_solarsystem = parsed_msg['message'].split(':')[1].strip()
#             print(f'You just jumped to {current_solarsystem}')
#             g.edge(current_solarsystem, last_solarsystem)
#             g.render(filename='eve.dot')

# Filter: fires every time you pass a stargate and sets your current solar system
async def system_locator_filter(msg):
    global current_solarsystem
    last_solarsystem = current_solarsystem
    if msg.username == "EVE System":
        system_change = msg.message.find('Channel changed to Local :')
        if system_change != '-1':
            current_solarsystem = msg.message.split(':')[1].strip()
            print(f'You just jumped to {current_solarsystem}')

# Filter: fires if someone mention you in a chat
async def name_filter(msg):
    user = [name for name in usernames if name in msg.message]
    if user:
        print(f"The Pilot {msg.username} wants to talk to you")
        await mqtttrigger('plug4')

# Filter: fires if someone is on the proximity list you made
#          should be automatic one day
async def proximity_filter(msg):
    solarsystem = [name for name in solarsystemlist if name in msg.message]
    if solarsystem:
        print(f'RUN .. enemy in {solarsystem}')
        await mqtttrigger('plug3')


chat_line_delimiter = u"\ufeff"
async def parselog( log ):
    # eve log files are utf-16 encoded
    async with aiofiles.open(log, mode='r',encoding="utf-16-le") as f:
        # dont like this code much - I needed to add the sleep
        # nicer would be if aiofile would not exit on EOL 
        # and would work without a context manager
        while True:
            line = await f.readline()
            # remove the weird UTF-16 thingy
            contents = line.strip(chat_line_delimiter)
            await asyncio.sleep(0.01)
            
            if contents and start_logging:
                msg = await parse_msg(contents)
                if msg:
                    print(msg)
                    # apply this filters
                    await system_locator_filter(msg)
                    await name_filter(msg)
                    await proximity_filter(msg)
            

async def start():
    await asyncio.sleep(0)
    global start_logging
    start_logging = True

async def status():
    while True:
        print('-----  STATUS -----')
        print(f'You are in {current_solarsystem}')
        print(f'reported ships in your area .. implement me !')
        await asyncio.sleep(30)
        

async def main():
    tasks = []        
    for log in chats:
        task = asyncio.create_task( parselog(log) )
        tasks.append(task)
    
    # add status monitor 
    #task = asyncio.create_task( status() )
    #tasks.append(task)
    
    # add start logging after reading the log files
    task = asyncio.create_task( start() )
    tasks.append(task)
    
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
