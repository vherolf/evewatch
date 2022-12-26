from datetime import datetime
from pathlib import Path
import asyncio, aiofiles
import time
import re
from dataclasses import dataclass
import asyncio_mqtt as aiomqtt
import paho.mqtt as mqtt

# at startup loggind is disabled. (otherwise all old log files entries are filtered)
start_logging = False
# changed the first time you jump to another system
current_solarsystem = ''
# turn on/off mqtt triggers
mqtt = True

today = datetime.now()
# searches you chatlog directory
chatlogdir = list(Path.home().rglob( 'EVE/logs/Chatlogs' )).pop()

# check for mentions of this usernames
usernames = ['Vherolf']

# solar systems that should be watched 
solarsystemlist = ['MVCJ-E','MVC','BK4-YC','2-TEGJ','LF-2KP','F-YH5B','K1I1-J','BK4','BK4-']

@dataclass(frozen=True, slots=True)
class Channel:
    channel: str
    path: Path

# all chatfiles from today
chatfiles = chatlogdir.glob( '*'+'_'+str(today.year) + str(today.month) + str(today.day)+'*.txt' )


# Filter: fires every time you pass a stargate and sets your current solar system
async def system_locator_filter(msg):
    global current_solarsystem
    last_solarsystem = current_solarsystem
    
    system_change = msg.message.find('Channel changed to Local :')
    if system_change != '-1':
        current_solarsystem = msg.message.split(':')[1].strip()
        print(f'Your new location is {current_solarsystem}')

# Filter: fires if someone mention you in a chat
async def name_filter(msg):
    user = [name for name in usernames if name in msg.message]
    if user:
        print(f"The Pilot {msg.username} wants to talk to you")
        if mqtt:
            await mqtttrigger('plug4')

# Filter: fires if someone is on the proximity list you made
#          should be automatic one day
async def proximity_filter(msg):
    solarsystem = [name for name in solarsystemlist if name in msg.message]
    if solarsystem:
        print(f'RUN .. enemy in {solarsystem}')
        if mqtt:
            await mqtttrigger('plug3')

# Trigger: sends a mqtt message (in this case it toggles a plug with a lamp)
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
    channel: Channel

## this function is from https://github.com/andrewpmartinez/py-eve-chat-mon (THANK YOU!)
async def parse_msg(raw_msg, channel) -> Message:
    line_parser = re.compile('^\s*\[\s(.*?)\s\]\s(.*?)\s>\s(.*?)$', re.DOTALL)
    match = line_parser.match(raw_msg)
    if match:
        timestamp = match.group(1)
        username = match.group(2)
        message = match.group(3)
        timestamp = datetime.strptime(timestamp, "%Y.%m.%d %H:%M:%S")

        parsed_msg = Message(timestamp = timestamp,
                      username = username,
                      message = message,
                      channel = channel)
        print(parsed_msg)
        return parsed_msg

    return None


# here is all glued together
chat_line_delimiter = u"\ufeff"
async def parse_log( chat ):
    # eve log files are utf-16 encoded
    async with aiofiles.open(chat.path, mode='r',encoding="utf-16-le") as f:
        # dont like this code much - I needed to add the sleep
        # nicer would be if aiofile would not exit on EOL 
        # and would work without a context manager
        while True:
            line = await f.readline()
            # remove the weird UTF-16 thingy
            raw_msg = line.strip(chat_line_delimiter)
            await asyncio.sleep(0.01)
            
            if raw_msg and start_logging:
                msg = await parse_msg(raw_msg=raw_msg, channel=chat)
                # apply filters
                match msg:
                    case Message(username='EVE System'):
                        await system_locator_filter(msg)
                    case Message(username='Message'):
                        print(msg.username, msg.message)
                    case _:
                        await proximity_filter(msg)
                        await name_filter(msg)
                

# status report is you want regular reports
async def status():
    while True:
        print('-----  STATUS -----')
        print(f'You are in {current_solarsystem}')
        print(f'reported ships in your area 3 jumps away.. implement me !')
        print(f'reported ships in your area 6 jumps away.. implement me !')
        await asyncio.sleep(30)

# delay logging while all old messages from chat logs are parsed
async def startup_log_delay(time=10):
    await asyncio.sleep(time)
    global start_logging
    start_logging = True

async def main():
    tasks = []
    for chatfile in chatfiles:
        print(chatfile)
        task = asyncio.create_task( parse_log(Channel(chatfile.stem,chatfile)) )
        tasks.append(task)
    
    # add status monitor 
    #task = asyncio.create_task( status() )
    #tasks.append(task)
    
    # add start logging after reading the log files
    task = asyncio.create_task( startup_log_delay() )
    tasks.append(task)
    
    await asyncio.gather(*tasks, return_exceptions=True)

if __name__ == "__main__":
    asyncio.run(main())
