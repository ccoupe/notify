#!/usr/bin/env python3
import paho.mqtt.client as mqtt
import sys
import json
import argparse
import warnings
from datetime import datetime
import time
import time, threading
import socket
import os
import platform
from subprocess import Popen
from lib.Settings import Settings
from lib.Homie_MQTT import Homie_MQTT
#import urllib.request
import logging
import logging.handlers
from pathlib import Path

from demo_opts import get_device
#from luma.core.virtual import terminal
from luma.core.render import canvas
from PIL import Image,ImageDraw,ImageFont
#
# Todo
#  demo - listen for flag set by cmd: off command
#  remove fonts dir? Will always have something in /usr/share
#
# globals
settings = None
hmqtt = None
debug_level = 1
isPi = False
applog = None
device = None
#term = None
cvs = None
font1 = None
font2 = None
font3 = None
devFnt = None   #default font 
devLnH = None   #default Line Height in pixels
background = None
cmdRun = True
notify_thread = None
scroll_thread = None
textLines =[]
devLns = 2

# no message for 5 minutes, stop the display and any scrolling
def notify_timer_fired():
  global scroll_thread, notify_thread
  notify_thread = None
  applog.info('TMO fired')
  if scroll_thread:
    scroll_thread.cancel()
    scroll_thread = None
  device.hide()

def notify_timer(secs):
  global notify_thread
  if notify_thread:
    # reset unfired timer by canceling.
    notify_thread.cancel()
  
  notify_thread = threading.Timer(secs, notify_timer_fired)
  notify_thread.start()

def set_font(fnt):
  global applog, devFnt, devLnH, settings,devLns, device
  if fnt == 2:
    devFnt = font2
    devLnH = settings.font2sz[1] # ex: 16
  elif fnt == 3:
    devFnt = font3
    devLnH = settings.font3sz[1] # ex: 21
  else:
    devFnt = font1 
    devLnH = settings.font1sz[1] # ex: 32
  devLns = int(device.height/devLnH)        # number of lines = device.height/Font_Height
  applog.info(f'devLnH: {devLnH}')
  applog.info(f'devLns: {devLns}={device.height}/{devLnH}')

def parseSettings(dt):
  global devFnt, font1, font2, font3
  print(f'parseSettings: {dt}')
  if dt['font']:
    set_font(dt['font'])
  
def cmdOff(args):
  global cmdRun, applog, device
  cmdRun = False
  applog.info('cmdOff')
  device.hide()
  
def cmdOn(args):
  global cmdRun, applog, device
  cmdRun = True
  applog.info('cmdOn')
  device.show()
  
  
# V1 - text arrives on display/text/set
#      cmds arrive on display/cmd/set as json
# V2 - text arrives as json on dist/cmd/set as json
#      cmds arrive on display/cmd/set as json

def cmdCb(payload):
  if payload[0] == '{':
    #print("Json: ", payload)
    args = json.loads(payload)
    cmd = args.get('cmd', None)
    setargs = args.get('settings', None);
    textargs = args.get('text')
    if cmd: 
      if cmd == 'on':
        cmdOn(args)
      elif cmd == 'off':
        cmdOff(args)
      elif cmd == 'demo':   # easter egg
        demo()
      elif cmd == 'update':
        applog.info('ignoring update command')
      else:
        applog.info("invalid command")
    elif setargs:
      parseSettings(setargs)
    elif textargs:
      applog.info("V2: not implemented yet")
    else:
      applog.info(f'valid command? {payload}')
  else:
    applog.info(f'Not json {payload}')
    
def leading(word):
  return int(max(0, (8 - len(word))/2))
  
  
def textCb(payload):
  global devFnt, devLnH, cmdRun, device, textLines, devLns
  global scroll_thread
  # should not have json for this call back
  if payload[0] == '{':
    applog.warn("no json processed on text/set")
  device.clear()
  cmdRun = True
  words = payload.split()
  nwd = len(words)
  notify_timer(5*60)
  device.show()
  textLines = []
  if scroll_thread:
    scroll_thread.cancel()
    
  needscroll = layoutLines(textLines, devLns, nwd, words)
  if needscroll:
    # set 1 sec timer
    scroll_thread =  threading.Timer(1, scroll_timer_fired)
    scroll_thread.start()
    #applog.info(f'setup scroll for {len(textLines)} lines')
    displayLines(0, devLns, textLines)
  else:
    displayLines(0, devLns, textLines)
    
# returns True if we need to scroll 
def layoutLines(lns, nln, nwd, words):
  lns.clear()
  #applog.info(f'layoutlines: {nln} {nwd} {words}')
  with canvas(device, dither=True) as draw:
    if nwd <= nln:
        y = 0
        for wd in words:
          wid = draw.textlength(wd, font=devFnt)
          lns.append(wd)
          y += devLnH
    else: 
      ln = ""
      wid = 0
      y = 0
      for wd in words:
        w = draw.textlength(' '+wd, font=devFnt)
        if (wid + w) > device.width:
          lns.append(ln)
          wid = 0
          ln = ""
          y += devLnH
        if wid == 0:
          ln = wd
          wid = w
          #applog.info(f'first word |{ln}|{wid}')
        else:
          ln = ln+' '+wd
          wid = draw.textlength(ln, font=devFnt)
          #applog.info(f'partial |{ln}|')

      # anything left over in ln ?
      if wid > 0:
        lns.append(ln)
        
  return len(lns) > nln


# st is index (0 based), end 1 higher  
def displayLines(st, end, textLines):
  global device, devLnH, firstLine,applog 
  firstLine = st
  device.clear()
  #applog.info(f'dspL {st} {end}')
  if len(textLines) < end:
    end = len(textLines)
    #applog.info(f'fixing up end to {end}')
  with canvas(device, dither=True) as draw:
    y = 0
    for i in range(st, end):
      wid = draw.textlength(textLines[i], font=devFnt)
      x = (device.width - wid)/2
      draw.multiline_text((x,y), textLines[i], font=devFnt, fill=stroke_fill)
      y += devLnH

# need to track the top line # displayed: global firstLine, 0 based.
def scroll_timer_fired():
  global firstLine, textLines, nlns, devLns, scroll_thread
  #applog.info(f'scroll firstLine: {firstLine}')
  firstLine = firstLine + devLns
  maxl = len(textLines)
  if firstLine > maxl:
    # at the end, roll over
    firstLine = 0
  end = min(firstLine + devLns, maxl)
  displayLines(firstLine, end, textLines)
  scroll_thread =  threading.Timer(1, scroll_timer_fired)
  scroll_thread.start()
  
def demo():
  global device, cmdRun
  img_path = str(Path(__file__).resolve().parent.joinpath('images', 'pi_logo.png'))
  logo = Image.open(img_path).convert("RGBA")
  fff = Image.new(logo.mode, logo.size, (255,) * 4)
  
  background = Image.new("RGBA", device.size, "white")
  posn = ((device.width - logo.width) // 2, 0)
  
  while cmdRun:
      for angle in range(0, 360, 2):
          rot = logo.rotate(angle, resample=Image.BILINEAR)
          img = Image.composite(rot, fff, rot)
          background.paste(img, posn)
          device.display(background.convert(device.mode))
          if not cmdRun:
            return
            
def main():
  global settings, hmqtt, applog, device, stroke_fill
  global devFnt, devLnH, background, foreground
  global font1, font2, font3
  # process cmdline arguments
  loglevels = ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')
  ap = argparse.ArgumentParser()
  ap.add_argument("-c", "--conf", required=True, type=str,
    help="path and name of the json configuration file")
  ap.add_argument("-s", "--syslog", action = 'store_true',
    default=False, help="use syslog")
  ap.add_argument("-d", "--debug", action='store', type=int, default='3',
    nargs='?', help="debug level, default is 3")
  args = vars(ap.parse_args())
  
  # logging setup
  applog = logging.getLogger('mqttnotify')
  #applog.setLevel(args['log'])
  if args['syslog']:
    applog.setLevel(logging.DEBUG)
    handler = logging.handlers.SysLogHandler(address = '/dev/log')
    # formatter for syslog (no date/time or appname. Just  msg.
    formatter = logging.Formatter('%(name)s-%(levelname)-5s: %(message)-40s')
    handler.setFormatter(formatter)
    applog.addHandler(handler)
  else:
    logging.basicConfig(level=logging.DEBUG,datefmt="%H:%M:%S",format='%(asctime)s %(levelname)-5s %(message)-40s')

  settings = Settings(args["conf"], 
                      applog)
  hmqtt = Homie_MQTT(settings, 
                    cmdCb,
                    textCb)
  settings.print()
  # 
  # device is object of class luma.oled.device.*
  #
  
  device = get_device(settings.luma_args)
  applog.info(f'device: {device.height}, {device.width}')
  font1 = ImageFont.truetype(settings.font1, settings.font1sz[0])
  font2 = ImageFont.truetype(settings.font2, settings.font2sz[0])
  font3 = ImageFont.truetype(settings.font2, settings.font3sz[0])
  fnt = settings.deflt_font
  set_font(fnt)
  stroke_fill = settings.stroke_fill  # color
  
  # fix debug levels
  if args['debug'] == None:
    debug_level = 3
  else:
    debug_level = args['debug']
    
  # All we do now is loop over a 5 minute delay
  while True:
    time.sleep(5*60)
  
if __name__ == '__main__':
  sys.exit(main())
