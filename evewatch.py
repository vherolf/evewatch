from datetime import datetime
from pathlib import Path
import asyncio, aiofiles
import time
import re
import asyncio_mqtt as aiomqtt
import paho.mqtt as mqtt

today = datetime.now()
# steam chat logs - change that accodingly to your system
#chatlogdir = Path(Path.home(),'.steam/debian-installation/steamapps/compatdata/8500/pfx/drive_c/users/steamuser/Documents/EVE/logs/Chatlogs')
chatlogdir = list(Path.home().rglob( 'EVE/logs/Chatlogs' )).pop()
print( "Chat log directory: ", chatlogdir )
# chat channel you wanna check
channellist = ['AKIMA WH_','INTEL.RC_','Local_','Heavy Metal Pirates_']
# check for mentions of this usernames
usernames = ['VHEROLF']

# make the chatlognames from today with pathlib glob and the channellist
chats=[]
for channel in channellist:
    chats += list(chatlogdir.glob(channel+str(today.year) + str(today.month) + str(today.day)+'*'))

# solar systems that should be watched 
solarsystemlist = ['MVCJ-E','MVC','BK4-YC','2-TEGJ','LF-2KP','F-YH5B','K1I1-J','BK4','BK4-']

async def mqtttrigger(plug="plug3"):
    async with aiomqtt.Client(hostname="hass.lan",
                              username="mqttmqtt",
                              password="mqttmqtt") as client:
        await client.publish(f"eve/{plug}", payload=f"TOGGLE")

## this function is from https://github.com/andrewpmartinez/py-eve-chat-mon
## thank you !
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
        # dont like this code much - it reads always
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
                    print(parsed_msg['timestamp'], parsed_msg['username'],parsed_msg['message'])
                    solarsystem =[name for name in solarsystemlist if name in parsed_msg['message']]
                    if solarsystem:
                        print(f'RUN .. enemy in {solarsystem}')
                        await mqtttrigger('plug3')
                    user = [name for name in usernames if name in parsed_msg['message'].upper()]
                    if user:
                        print(f"The Pilot {parsed_msg['username']} wants to talk to you")
                        await mqtttrigger('plug4')
          
async def main():
    tasks = []        
    for log in chats:
        task = asyncio.create_task( parselog(log) )
        tasks.append(task)
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
