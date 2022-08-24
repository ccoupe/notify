#!/usr/bin/env python3
import paho.mqtt.client as mqtt
import sys, traceback
import json
from datetime import datetime
from threading import Thread
import time

import time

class Homie_MQTT:

  def __init__(self, settings, cmdCb, textCb):
    self.settings = settings
    self.log = settings.log
    self.cmdCb = cmdCb
    self.textCb = textCb
    # init server connection
    self.client = mqtt.Client(settings.mqtt_client_name, False)
    self.client.reconnect_delay_set(min_delay=1, max_delay=60)
    #self.client.max_queued_messages_set(3)

    hdevice = self.hdevice = self.settings.homie_device  # "device_name"
    hlname = self.hlname = self.settings.homie_name     # "Display Name"
    # beware async timing with on_connect
    #self.client.on_connect = self.on_connect
    #self.client.on_subscribe = self.on_subscribe
    self.client.on_message = self.on_message
    self.client.on_disconnect = self.on_disconnect
    rc = self.client.connect(settings.mqtt_server, settings.mqtt_port)
    if rc != mqtt.MQTT_ERR_SUCCESS:
        self.log.warn("network missing?")
        exit()
    self.client.loop_start()
    self.hsubDspCmd = f"homie/{self.hdevice}/display/cmd/set"
    self.hsubDspTxt = f"homie/{self.hdevice}/display/text/set"
    self.listen_to = [self.hsubDspCmd, self.hsubDspTxt]
    for topic in settings.listen:
      self.listen_to.append(topic)
      
    # self.log.debug("Homie_MQTT __init__")
    self.create_topics(hdevice, hlname)
    for sub in self.listen_to:    
      rc,_ = self.client.subscribe(sub)
      if rc != mqtt.MQTT_ERR_SUCCESS:
        self.log.warn("Subscribe failed: %d" %rc)
      else:
        self.log.debug("Init() Subscribed to %s" % sub)
      
     
  def create_topics(self, hdevice, hlname):
    self.log.debug("Begin topic creation")
    # create topic structure at server - these are retained! 
    self.publish_structure("homie/"+hdevice+"/$homie", "3.0.1")
    self.publish_structure("homie/"+hdevice+"/$name", hlname)
    self.publish_structure("homie/"+hdevice+"/$state", "ready")
    self.publish_structure("homie/"+hdevice+"/$mac", self.settings.macAddr)
    self.publish_structure("homie/"+hdevice+"/$localip", self.settings.our_IP)
    # could have two nodes, display and autoranger
    self.publish_structure("homie/"+hdevice+"/$nodes", "display")
    
    # display node
    self.publish_structure("homie/"+hdevice+"/display/$name", hlname)
    self.publish_structure("homie/"+hdevice+"/display/$type", "display")
    self.publish_structure("homie/"+hdevice+"/display/$properties", "cmd,text")
    # cmd Property of 'display'
    self.publish_structure("homie/"+hdevice+"/display/cmd/$name", hlname)
    self.publish_structure("homie/"+hdevice+"/display/cmd/$datatype", "string")
    self.publish_structure("homie/"+hdevice+"/display/cmd/$settable", "false")
    self.publish_structure("homie/"+hdevice+"/display/cmd/$retained", "true")
    # text Property of 'display'
    self.publish_structure("homie/"+hdevice+"/display/text/$name", hlname)
    self.publish_structure("homie/"+hdevice+"/display/text/$datatype", "string")
    self.publish_structure("homie/"+hdevice+"/display/text/$settable", "false")
    self.publish_structure("homie/"+hdevice+"/display/text/$retained", "true")
  
    # Done with structure. 

    self.log.debug("homie topics created")
    # nothing else to publish 
    
  def publish_structure(self, topic, payload):
    self.client.publish(topic, payload, qos=1, retain=True)
    
  def on_subscribe(self, client, userdata, mid, granted_qos):
    self.log.debug("Subscribed to %s" % self.hurl_sub)

  def on_message(self, client, userdata, message):
    settings = self.settings
    topic = message.topic
    payload = str(message.payload.decode("utf-8"))
    self.log.debug("on_message %s %s" % (topic, payload))
    try:
      for lstn in self.listen_to:
        if topic == lstn:
          if topic == self.hsubDspTxt:
            ply_thr = Thread(target=self.textCb, args=(payload,))
            ply_thr.start()
          elif topic == self.hsubDspCmd:
            ply_thr = Thread(target=self.cmdCb, args=(payload,))
            ply_thr.start()
          else:
            ply_thr = Thread(target=self.textCb, args=(payload,))
            ply_thr.start()
        
    except:
      traceback.print_exc()

    
  def isConnected(self):
    return self.mqtt_connected

  def on_connect(self, client, userdata, flags, rc):
    if rc != mqtt.MQTT_ERR_SUCCESS:
      self.log.warn("Connection failed")
      self.mqtt_connected = False
      time.sleep(60)
      self.client.reconnect()
    else:
      self.mqtt_connected = True
       
  def on_disconnect(self, client, userdata, rc):
    self.mqtt_connected = False
    self.log.warn(f"mqtt disconnect: {rc}, attempting reconnect")
    self.client.reconnect()
      
  def set_status(self, str):
    self.client.publish(self.state_pub, str)
