"""Local, dependency-free presentation components for Twin Finder."""
import math
import os
import time
import tkinter as tk
from tkinter import ttk
from app_platform import UI_FONT

COLORS = {
    'canvas': '#000000', 'surface': '#000000', 'sidebar': '#000000',
    'card': '#0C0C0C', 'text': '#F5F5F5', 'muted': '#AAAAAA',
    'line': '#262626', 'accent': '#D8E7E5', 'hover': '#E5E5E5',
    'selection': '#1C1C1C', 'subtle': '#141414',
}


def enable_high_dpi():
    """Set awareness before Tk creates an HWND; never change Windows settings.

    The packaged executable declares this in its manifest. The API path is for
    running desktop.py with the ordinary, DPI-unaware Python interpreter.
    """
    if os.name!='nt':return
    import ctypes
    user32=ctypes.WinDLL('user32',use_last_error=True)
    try:
        set_context=user32.SetProcessDpiAwarenessContext
        set_context.argtypes=[ctypes.c_void_p];set_context.restype=ctypes.c_bool
        if set_context(ctypes.c_void_p(-4)):return  # Per-monitor v2.
        if ctypes.get_last_error()==5:return  # Already set by the manifest/host.
    except AttributeError:pass
    try:
        result=ctypes.windll.shcore.SetProcessDpiAwareness(2)
        if result in (0,-2147024891):return
    except (AttributeError,OSError):pass
    user32.SetProcessDPIAware()


def create_root():
    enable_high_dpi()
    return tk.Tk()


def configure_theme(root):
    c=COLORS
    root.configure(background=c['canvas'])
    # A *Font option would become a widget-level override and defeat Ttk styles.
    root.option_add('*TCombobox*Listbox.background',c['card'])
    root.option_add('*TCombobox*Listbox.foreground',c['text'])
    root.option_add('*TCombobox*Listbox.selectBackground',c['selection'])
    root.option_add('*TCombobox*Listbox.selectForeground',c['text'])
    style=ttk.Style(root);style.theme_use('clam')
    style.configure('.',font=(UI_FONT,10),background=c['surface'],foreground=c['text'])
    for name,bg in [('TFrame',c['surface']),('Chrome.TFrame',c['canvas']),('Sidebar.TFrame',c['sidebar']),('Card.TFrame',c['card'])]:
        style.configure(name,background=bg)
    style.configure('TLabel',background=c['surface'],foreground=c['text'],anchor='w')
    style.configure('Muted.TLabel',foreground=c['muted'])
    style.configure('Chrome.TLabel',background=c['canvas'],foreground=c['muted'])
    style.configure('Heading.TLabel',font=(UI_FONT,46),background=c['canvas'])
    style.configure('Hero.TLabel',font=(UI_FONT,30),background=c['canvas'])
    style.configure('Sub.TLabel',font=(UI_FONT,13,'bold'))
    style.configure('Kicker.TLabel',font=(UI_FONT,9,'bold'),foreground=c['muted'])
    style.configure('Banner.TLabel',font=(UI_FONT,10),foreground=c['muted'])
    style.configure('Sidebar.TLabel',background=c['sidebar'],foreground=c['muted'])
    style.configure('Count.TLabel',background=c['sidebar'],font=(UI_FONT,27),foreground=c['text'])
    style.configure('Card.TLabel',background=c['card'])
    style.configure('CardMuted.TLabel',background=c['card'],foreground=c['muted'])
    style.configure('CardTitle.TLabel',background=c['card'],font=(UI_FONT,12,'bold'))
    style.configure('Score.TLabel',background=c['card'],font=(UI_FONT,25),foreground=c['accent'])
    style.configure('TButton',padding=(16,11),background=c['card'],foreground=c['text'],
                    bordercolor=c['line'],lightcolor=c['card'],darkcolor=c['card'],borderwidth=1,relief='flat')
    style.map('TButton',background=[('disabled',c['sidebar']),('pressed',c['selection']),('active',c['subtle'])],
              foreground=[('disabled','#78828C')],bordercolor=[('focus',c['accent'])])
    style.configure('Primary.TButton',background=c['text'],foreground=c['canvas'],
                    bordercolor=c['text'],lightcolor=c['text'],darkcolor=c['text'])
    style.map('Primary.TButton',background=[('disabled',c['line']),('pressed',c['accent']),('active',c['hover'])],
              foreground=[('disabled',c['muted']),('!disabled',c['canvas'])],
              bordercolor=[('focus',c['accent']),('!disabled',c['text'])])
    style.configure('Nav.TButton',anchor='w',padding=(14,10),background=c['sidebar'],borderwidth=0)
    style.configure('Active.Nav.TButton',background=c['selection'],foreground=c['text'])
    style.map('Active.Nav.TButton',background=[('active',c['selection']),('!disabled',c['selection'])])
    style.configure('Quiet.TButton',padding=(10,6),borderwidth=0,background=c['surface'],foreground=c['muted'])
    for name in ('TEntry','TCombobox'):
        style.configure(name,padding=7,fieldbackground=c['card'],foreground=c['text'],
                        bordercolor=c['line'],lightcolor=c['card'],darkcolor=c['card'],arrowsize=12,
                        insertcolor=c['text'],selectbackground=c['selection'],selectforeground=c['text'])
        style.map(name,bordercolor=[('focus',c['accent'])],
                  fieldbackground=[('disabled',c['sidebar']),('readonly',c['card'])],
                  foreground=[('disabled',c['muted']),('readonly',c['text'])])
    style.configure('TNotebook',background=c['canvas'],borderwidth=0,
                    bordercolor=c['canvas'],lightcolor=c['canvas'],darkcolor=c['canvas'])
    style.layout('TNotebook',[('Notebook.client',{'sticky':'nswe'})])
    style.layout('TNotebook.Tab',[])
    style.configure('Treeview',rowheight=30,background=c['card'],fieldbackground=c['card'],
                    bordercolor=c['line'],lightcolor=c['line'],darkcolor=c['line'],borderwidth=0)
    style.configure('Treeview.Heading',font=(UI_FONT,10,'bold'),background=c['subtle'],
                    foreground=c['muted'],padding=(10,8),relief='flat')
    style.map('Treeview',background=[('selected',c['selection'])],foreground=[('selected',c['text'])])
    style.map('Treeview.Heading',background=[('active',c['line'])])
    style.configure('TScrollbar',background=c['line'],troughcolor=c['surface'],borderwidth=0,arrowsize=10,
                    bordercolor=c['surface'],lightcolor=c['line'],darkcolor=c['line'])
    style.layout('Vertical.TScrollbar',[('Vertical.Scrollbar.trough',{'sticky':'ns',
                 'children':[('Vertical.Scrollbar.thumb',{'sticky':'nswe'})]})])
    style.map('TScrollbar',background=[('active','#555555')])
    style.configure('TSeparator',background=c['line'])
    style.configure('Horizontal.TProgressbar',background=c['accent'],troughcolor=c['line'],
                    borderwidth=0,thickness=4,lightcolor=c['accent'],darkcolor=c['accent'])


class Card(tk.Canvas):
    """Rounded card with ordinary, selectable/focusable widgets inside it."""
    def __init__(self,parent,padding=20,**kwargs):
        super().__init__(parent,background=COLORS['surface'],highlightthickness=0,width=1,height=120,**kwargs)
        self.padding=padding
        self.panel=self.create_polygon(0,0,0,0,fill=COLORS['card'],outline=COLORS['line'],smooth=True)
        self.body=ttk.Frame(self,style='Card.TFrame')
        self.window=self.create_window(padding,padding,window=self.body,anchor='nw')
        self.bind('<Configure>',self.resize)
        self.body.bind('<Configure>',self.resize)

    def resize(self,event=None):
        w=max(2,self.winfo_width());h=max(2,self.winfo_height());r=14
        points=[r,1,w-r,1,w-1,1,w-1,r,w-1,h-r,w-1,h-1,w-r,h-1,r,h-1,1,h-1,1,h-r,1,r,1,1]
        self.coords(self.panel,*points)
        self.itemconfigure(self.window,width=max(1,w-2*self.padding))
        desired=self.body.winfo_reqheight()+2*self.padding
        if int(self.cget('height'))!=desired:self.configure(height=desired)


class ReviewTrack(tk.Canvas):
    """A thin progress line without native-theme trough borders."""
    def __init__(self,parent):
        super().__init__(parent,width=1,height=4,background=COLORS['sidebar'],highlightthickness=0)
        self.fraction=0
        self.bind('<Configure>',self.draw)

    def set(self,value,maximum):
        self.fraction=max(0,min(1,value/max(1,maximum)));self.draw()

    def draw(self,event=None):
        self.delete('all');width=max(1,self.winfo_width())
        self.create_rectangle(0,0,width,4,fill=COLORS['line'],outline='')
        if self.fraction:self.create_rectangle(0,0,width*self.fraction,4,fill=COLORS['accent'],outline='')


class SimilarityBar(ttk.Frame):
    def __init__(self,parent,label):
        super().__init__(parent)
        self.columnconfigure(1,weight=1)
        ttk.Label(self,text=label,style='Muted.TLabel',width=20).grid(row=0,column=0,sticky='w',padx=(0,16))
        self.track=tk.Canvas(self,height=12,width=1,background=COLORS['surface'],highlightthickness=0)
        self.track.grid(row=0,column=1,sticky='ew')
        self.value=tk.StringVar(value='—')
        ttk.Label(self,textvariable=self.value,width=8,anchor='e').grid(row=0,column=2,sticky='e',padx=(16,0))
        self.fraction=None
        self.track.bind('<Configure>',self.draw)

    def set(self,value):
        self.fraction=None if value is None else max(0,min(1,float(value)))
        self.value.set('N/A' if value is None else f'{self.fraction:.0%}')
        self.draw()

    def draw(self,event=None):
        c=self.track;c.delete('all');w=max(12,c.winfo_width())
        c.create_line(5,6,w-5,6,fill=COLORS['line'],width=5,capstyle='round')
        if self.fraction:
            c.create_line(5,6,5+(w-10)*self.fraction,6,fill=COLORS['accent'],width=5,capstyle='round')


class ActivityRing(tk.Canvas):
    """Non-blocking activity animation, explicitly not a completion percentage."""
    def __init__(self,parent):
        super().__init__(parent,width=30,height=30,highlightthickness=0,background=COLORS['canvas'])
        self.running=False;self.timer=None;self.started=0;self.phase=0
        self.draw()
        self.bind('<Destroy>',self.destroyed,add='+')

    def start(self,interval=None):
        if self.running:return
        self.running=True;self.started=time.monotonic();self.phase=0;self.tick()

    def stop(self):
        self.running=False
        if self.timer is not None:self.after_cancel(self.timer);self.timer=None
        self.draw()

    def destroyed(self,event):
        if event.widget is self and self.timer is not None:
            self.after_cancel(self.timer);self.timer=None

    def tick(self):
        if not self.running:return
        self.phase=(self.phase+9)%360;self.draw()
        self.timer=self.after(40,self.tick)

    def draw(self):
        self.delete('all')
        if not self.running:
            self.create_oval(11,11,19,19,fill=COLORS['muted'],outline='');return
        self.create_oval(4,4,26,26,outline=COLORS['line'],width=2)
        extent=90+45*math.sin(math.radians(self.phase))
        self.create_arc(4,4,26,26,start=-self.phase,extent=extent,style='arc',outline=COLORS['accent'],width=3)


def wrap_label(parent,**kwargs):
    label=ttk.Label(parent,wraplength=300,**kwargs)
    label.bind('<Configure>',lambda e:label.configure(wraplength=max(40,e.width)))
    return label
