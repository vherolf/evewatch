from datetime import datetime
from pathlib import Path
import asyncio, aiofiles
import time
import re
import asyncio_mqtt as aiomqtt
import paho.mqtt as mqtt

# changed the first time you jump to another system
current_solarsystem = 'BK4-YC'

today = datetime.now()
chatlogdir = list(Path.home().rglob( 'EVE/logs/Chatlogs' )).pop()
# chat channel you wanna check
channellist = ['AKIMA WH','INTEL.RC','Local','Heavy Metal Pirates']
# check for mentions of this usernames
usernames = ['VHEROLF']

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

## this function is from https://github.com/andrewpmartinez/py-eve-chat-mon (THANK YOU!)
async def parse_msg(msg):
    line_parser = re.compile('^\s*\[\s(.*?)\s\]\s(.*?)\s>\s(.*?)$', re.DOTALL)
    match = line_parser.match(msg)
    if match:
        timestamp = match.group(1)
        username = match.group(2)
        message = match.group(3)
        message_hash = hash(message)
        timestamp = datetime.strptime(timestamp, "%Y.%m.%d %H:%M:%S")

        parsed_msg = {"timestamp": timestamp,
                      "username": username,
                      "message": message,
                      "line": msg,
                      "hash": message_hash}
        return parsed_msg

    return None

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
            
            if contents:
                parsed_msg = await parse_msg(contents)
                if parsed_msg:
                    print(parsed_msg['timestamp'], parsed_msg['username'],'>',parsed_msg['message'])
                    solarsystem =[name for name in solarsystemlist if name in parsed_msg['message']]
                    if solarsystem:
                        print(f'RUN .. enemy in {solarsystem}')
                        await mqtttrigger('plug3')
                    user = [name for name in usernames if name in parsed_msg['message'].upper()]
                    if user:
                        print(f"The Pilot {parsed_msg['username']} wants to talk to you")
                        await mqtttrigger('plug4')
                    if parsed_msg['username'] == "EVE System":
                        system_change = parsed_msg['message'].find('Channel changed to Local :')
                        if system_change != '-1':
                            current_solarsystem = parsed_msg['message'].split(':')[1]
                            print(f'You are in {current_solarsystem} now')
          
async def main():
    tasks = []        
    for log in chats:
        task = asyncio.create_task( parselog(log) )
        tasks.append(task)
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
