#!/usr/bin/python3

import sys
import subprocess
import re
from datetime import datetime, timedelta
import time
from Xlib import display, Xatom
from multiprocessing import Process, Event, Queue
from evdev import InputDevice, list_devices, categorize, ecodes

'''
a stupid class to hold information about windows
'''
class WindowInfo:
    def __init__(self, parent, id, name, cls, width, height, x, y, fullscreen, visible, focused, onprimary):
        self.id = id
        self.parent = parent
        self.name = name
        self.cls = cls
        self.width = width
        self.height = height
        self.x = x
        self.y = y
        self.fullscreen = fullscreen
        self.visible = visible
        self.focused = focused
        self.onprimary = onprimary
        self.children = []
    def anyparentvisible(self):
        parent = self
        while parent != None:
            if parent.visible:
                return True
            parent = parent.parent
        return False
    def anyparentfullscreen(self):
        parent = self
        while parent != None:
            if parent.fullscreen:
                return True
            parent = parent.parent
        return False
    def anyparentfocused(self):
        parent = self
        while parent != None:
            if parent.focused:
                return True
            parent = parent.parent
        return False
    def anyparentnamecls(self, name):
        parent = self
        while parent != None:
            if parent.name and parent.name.find(name) > -1:
                return True
            if parent.cls and parent.cls.find(name) > -1:
                return True
            parent = parent.parent
        return False
    def anyparentonprimary(self):
        parent = self
        while parent != None:
            if parent.onprimary:
                return True
            parent = parent.parent
        return False

'''
this class enumerates all windows and builds a tree contining WindowInfo objects in their hierarchy
'''
class WindowHelper:
    def __init__(self):
        super(WindowHelper, self).__init__()
        
        self.display = display.Display()
        self.root = self.display.screen().root
        
        self.PRIMARY_SCREEN_X = 2560
        self.PRIMARY_SCREEN_WIDTH = 2560
    def outputtreefromtop(self, currentwindowinfo):
        parent = currentwindowinfo
        while parent != None:
            parent = parent.parent
    def outputtree(self, tree, currentwindowinfo, depth):
        #time.sleep(0.01)
        
        if currentwindowinfo == None:
            s = ''
            lst = tree
        else:
            attrs = ''
            if currentwindowinfo.fullscreen:
                attrs += ' fullscreen'
            if currentwindowinfo.visible:
                attrs += ' visible'
            if currentwindowinfo.focused:
                attrs += ' focused'
                
            s = ' ' * (depth * 2) + '- ' + str(currentwindowinfo.name) + ' (' + str(currentwindowinfo.cls) + ') ' + str(currentwindowinfo.id) + '\n'
            s += ' ' * (depth * 2) + '  ' + 'width: ' + str(currentwindowinfo.width) + ' height: ' + str(currentwindowinfo.height) + ' x: ' + str(currentwindowinfo.x) + ' / ' + attrs + '\n'
            lst = currentwindowinfo.children
        
        for windowinfo in lst:
            s += self.outputtree(tree, windowinfo, depth + 1)
        return s
    def buildtree(self):
        tree = []
        toplevelwindows = []
        def enum(windowparent, windowinfoparent):
            found = False
            for window in windowparent.query_tree()._data['children']:
                found = True
                
                geo = window.get_geometry()._data
                width = geo["width"]
                height = geo["height"]
                x = geo["x"]
                y = geo["y"]

                if width < 2560 or height < 1440:
                    continue

                state = window.get_property(self.display.get_atom('_NET_WM_STATE'), Xatom.ATOM, 0, 128)
                name = window.get_property(self.display.get_atom('WM_NAME'), Xatom.STRING, 0, 128)
                cls = window.get_property(self.display.get_atom('WM_CLASS'), Xatom.STRING, 0, 128)
                command = window.get_property(self.display.get_atom('WM_COMMAND'), Xatom.STRING, 0, 128)
                
                windowname = None
                classname = None
                hidden = None
                fullscreen = None
                
                if name != None:
                    windowname = str(name.value)
                
                if cls != None:
                    classname = str(cls.value)
                
                if state != None:
                    hidden = self.display.get_atom('_NET_WM_STATE_HIDDEN') in state.value
                    fullscreen = self.display.get_atom('_NET_WM_STATE_FULLSCREEN') in state.value
                
                onprimary = x >= self.PRIMARY_SCREEN_X and x <= self.PRIMARY_SCREEN_X + self.PRIMARY_SCREEN_WIDTH
                            
                windowinfo = WindowInfo(windowinfoparent, window.id, windowname, classname, width, height, x, y, fullscreen, not hidden, \
                    self.display.get_input_focus().focus.id == window.id, onprimary)
                
                if windowinfoparent == None:
                    tree.append(windowinfo)
                else:
                    windowinfoparent.children.append(windowinfo)

                enum(window, windowinfo)
            if not found:
                toplevelwindows.append(windowinfoparent)
        tries = 0
        while len(tree) == 0:
            try:
                enum(self.root, None)
            except:
                tree = []
                toplevelwindows = []
                print('error enumerating windows...')
                time.sleep(1)
        return tree, toplevelwindows

'''
this thread watches for fullscreen windows and triggers events which are
read in the App class which created this MouseHandler
'''
class MouseHandler(Process):
    def __init__(self, termevent):
        super(MouseHandler, self).__init__()
        
        self.termevent = termevent        
        
        self.PRIMARY_SCREEN_X = 2560
        self.PRIMARY_SCREEN_WIDTH = 2560
        
        self.queue = Queue()
        self.lastfullscreencheck = datetime.now()
        self.lastappscheck = datetime.now()
        self.fullscreen = False
        self.apps = []
        
        self.display = display.Display()
        self.root = self.display.screen().root
        
        self.windowhelper = WindowHelper()
    def mousepos(self):
        data = self.root.query_pointer()._data
        return data["root_x"], data["root_y"]
    def loadapps(self):
        self.apps = []
        f = open('/home/alex/.scripts/ignoremovemouseapps.txt', 'r')
        try:
            for l in f.read().split('\n'):
                if l.strip() != '':
                    self.apps.append(l.strip())
        finally:
            f.close()
        lastappscheck = datetime.now()
    def enteredfullscreen(self):
        print('entered fullscreen')
        
        self.queue.put('enteredfullscreen')
    def leftfullscreen(self):
        print('left fullscreen')
        
        self.queue.put('leftfullscreen')
    def isfullscreen(self, lst):
        self.fullscreen = False
        
        toplevel = lst[1]
        lst = lst[0]
        
        for windowinfo in toplevel:
            f = False
            for a in self.apps:
                if windowinfo.anyparentnamecls(a):
                    f = True
                    break
            if f:
                continue
            
            if windowinfo.anyparentonprimary() and windowinfo.anyparentfocused() and windowinfo.anyparentfullscreen() and windowinfo.anyparentvisible():
                self.fullscreen = True
                break
        self.lastfullscreencheck = datetime.now()
    def run(self):
        try:
            self.loadapps()
            self.isfullscreen(self.windowhelper.buildtree())
            while True:
                wasfullscreen = self.fullscreen
                if self.lastappscheck + timedelta(seconds=5) < datetime.now():
                    self.loadapps()
                if self.lastfullscreencheck + timedelta(seconds=1) < datetime.now():
                    self.isfullscreen(self.windowhelper.buildtree())
                    if self.fullscreen != wasfullscreen:
                        if self.fullscreen:
                            self.enteredfullscreen()
                        else:
                            self.leftfullscreen()

                time.sleep(0.03)

                if self.termevent.is_set():
                    break
        except KeyboardInterrupt as e:
            return
        except Exception as e:
            print('Exception in MouseHandler')
            print(e)

class App:
    def __init__(self):
        self.xbarrierCmd = ['/home/alex/.scripts/xbarrier', '2560', '0', '2560', '1440', '1', ]

        self.xbarrierProcess = None
    def xbarrier(self, on):
        if on:
            self.xbarrier(False)
            print('starting xbarrier')
            self.xbarrierProcess = subprocess.Popen(self.xbarrierCmd)
        else:
            if self.xbarrierProcess != None:
                print('killing xbarrier...')
                self.xbarrierProcess.terminate()
                #self.xbarrierProcess.wait()
                self.xbarrierProcess = None
                print('xbarrier killed')            
    def run(self):
        termevent = Event()
        
        mh = None
        hh = None
        try:
            mh = MouseHandler(termevent)
            mh.start()
            
            while True:
                if not mh.is_alive():
                    self.xbarrier(False)
                    
                    print('MouseHandler died, restarting')
                    mh = MouseHandler(termevent)
                    mh.start()
                
                try:
                    item = mh.queue.get(False)
                    if item == 'enteredfullscreen':
                        self.xbarrier(True)
                    if item == 'leftfullscreen':
                        self.xbarrier(False)
                except:
                    pass
                
                time.sleep(0.1)
        except KeyboardInterrupt as e:
            termevent.set()
        except Exception as e:
            print('Exception in App')
            print(e)
            termevent.set()
        print('Waiting for thread/redshift/xbarrier termination...')
        self.xbarrier(False)
        mh.join()

app = App()
app.run()