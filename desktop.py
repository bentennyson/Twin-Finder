"""Desktop UI. Background tasks call the same services as cli.py."""
import argparse
import json
import queue
import threading
import traceback
import time
import sqlite3
import uuid
import progressive
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from tkinter import font as tkfont

import ai_model as ai
import storage
import twin_workflow as workflow


import twin_core as core
from app_platform import UI_FONT, recent_jobs_path
from modern_ui import COLORS, configure_theme, create_root, Card, SimilarityBar, ActivityRing, ReviewTrack, wrap_label


class App:
    def __init__(self,root,initial_job=None):
        self.root=root;root.title('Twin Finder — bibliographic data cleaning')
        self.ui_scale=max(1,root.winfo_fpixels('1i')/96)
        available_width=root.winfo_screenwidth()-80;available_height=root.winfo_screenheight()-100
        root.geometry(f'{min(round(1320*self.ui_scale),available_width)}x{min(round(820*self.ui_scale),available_height)}')
        root.minsize(min(round(960*self.ui_scale),available_width),min(round(650*self.ui_scale),available_height))
        self.messages=queue.Queue();self.cancel=threading.Event();self.busy=False;self.buttons=[];self.pending_close=False
        self.current=1;self.proposal=None;self.scan_mode=False;self.last_snapshot=0;self.first_shown=False
        self.review_pending=None;self.waiting_review=None;self.review_cooldown=0;self.review_timer=None
        self.ready_total=0;self.reviewed_count=0;self.progress_job=None;self.active_mapping={k:k for k in core_fields()}
        configure_theme(root)
        menu=tk.Menu(root);help_menu=tk.Menu(menu,tearoff=False)
        help_menu.add_command(label='Run diagnostics',command=lambda:self.guarded(self.diagnostics))
        file_menu=tk.Menu(menu,tearoff=False)
        file_menu.add_command(label='Open dataset…',command=lambda:self.guarded(self.open_dataset_file))
        file_menu.add_command(label='Open saved work…',command=lambda:self.guarded(self.open_job))
        file_menu.add_command(label='Processing limits…',command=lambda:self.guarded(self.processing_limits))
        self.recent_menu=tk.Menu(file_menu,tearoff=False);file_menu.add_cascade(label='Recent datasets',menu=self.recent_menu)
        self.update_recent_menu();menu.add_cascade(label='File',menu=file_menu);menu.add_cascade(label='Help',menu=help_menu)
        root.configure(menu=menu)
        self.status=tk.StringVar(value='Choose a dataset. AI finds candidates; you make the final decision.')
        self.job=tk.StringVar(value=str(initial_job) if initial_job else '')
        self.filename=tk.StringVar(value='No dataset selected')
        self.banner=tk.StringVar(value='Local processing  /  Human-in-the-loop review')
        shell=ttk.Frame(root);shell.pack(fill='both',expand=True)
        sidebar=ttk.Frame(shell,style='Sidebar.TFrame',padding=(22,18),width=round(228*self.ui_scale))
        sidebar.pack(side='left',fill='y');sidebar.pack_propagate(False)
        ttk.Label(sidebar,text='WORKSPACE',style='Sidebar.TLabel',font=(UI_FONT,9,'bold')).pack(anchor='w',pady=(0,18))
        main_area=ttk.Frame(shell);main_area.pack(side='left',fill='both',expand=True)
        main=ttk.Frame(main_area,padding=(28,18))
        main.place(relx=.5,y=0,anchor='n',relwidth=1,relheight=1)
        def fit_content(event):
            maximum=round(1260*self.ui_scale)
            main.place_configure(relwidth=0 if event.width>maximum else 1,width=maximum if event.width>maximum else 0)
        main_area.bind('<Configure>',fit_content)
        main.columnconfigure(0,weight=1);main.rowconfigure(1,weight=1)
        header=ttk.Frame(main);header.grid(row=0,column=0,sticky='ew',pady=(0,18));header.columnconfigure(0,weight=1)
        self.title_label=ttk.Label(header,text='Twin Finder',style='Heading.TLabel')
        self.title_label.grid(row=0,column=0,sticky='w')
        wrap_label(header,text='Human-in-the-loop review for bibliographic data cleaning.',style='Muted.TLabel').grid(row=1,column=0,sticky='ew',pady=(0,10))
        self.tabs=ttk.Notebook(main);self.tabs.grid(row=1,column=0,sticky='nsew')
        self.data_tab=ttk.Frame(self.tabs);self.review_tab=ttk.Frame(self.tabs);self.learn_tab=ttk.Frame(self.tabs)
        self.nav_buttons={}
        for frame,label in [(self.data_tab,'Dataset'),(self.review_tab,'Review pairs'),(self.learn_tab,'Learn and export')]:
            self.tabs.add(frame,text=label)
            b=ttk.Button(sidebar,text=label,style='Nav.TButton',command=lambda page=frame:self.tabs.select(page))
            b.pack(fill='x',pady=3);self.nav_buttons[str(frame)]=b
        self.tabs.bind('<<NotebookTabChanged>>',self.update_navigation)
        ttk.Separator(sidebar).pack(fill='x',pady=16)
        ttk.Label(sidebar,text='PAIRS REVIEWED',style='Sidebar.TLabel',font=(UI_FONT,9,'bold')).pack(anchor='w')
        self.review_count=tk.StringVar(value='0 / 0')
        self.count_label=ttk.Label(sidebar,textvariable=self.review_count,style='Count.TLabel');self.count_label.pack(fill='x',pady=(6,10))
        self.count_label.bind('<Configure>',lambda event:self.fit_review_count())
        self.review_progress=ReviewTrack(sidebar);self.review_progress.pack(fill='x')
        wrap_label(sidebar,text='Of the pairs ready so far. Skipped pairs remain unreviewed.',style='Sidebar.TLabel').pack(fill='x',pady=(8,14))
        ttk.Label(sidebar,text='YOUR DATASET',style='Sidebar.TLabel',font=(UI_FONT,9,'bold')).pack(anchor='w')
        self.short_filename=tk.StringVar(value=self.filename.get())
        self.filename.trace_add('write',self.update_short_filename)
        wrap_label(sidebar,textvariable=self.short_filename,style='Sidebar.TLabel').pack(fill='x',pady=(8,16))
        self.open_button=self.button(sidebar,'Open dataset  +',self.open_dataset_file,style='Primary.TButton');self.open_button.pack(fill='x',pady=(0,8))
        self.saved_button=self.button(sidebar,'Open saved work',self.open_job);self.saved_button.pack(fill='x',pady=(0,8))
        self.resume_button=self.button(sidebar,'Resume processing',self.resume_processing);self.resume_button.pack(fill='x')
        self.review_content=self.scroll_panel(self.review_tab)
        self.learn_content=self.scroll_panel(self.learn_tab)
        self.build_data();self.build_review();self.build_learning()
        self.layout_column(self.learn_content)
        footer=ttk.Frame(main);footer.grid(row=2,column=0,sticky='ew',pady=(12,0));footer.columnconfigure(1,weight=1)
        self.progress=ActivityRing(footer);self.progress.grid(row=0,column=0,rowspan=2,padx=(0,10))
        self.activity=tk.StringVar(value='Ready')
        ttk.Label(footer,textvariable=self.activity,style='Kicker.TLabel').grid(row=0,column=1,sticky='w')
        wrap_label(footer,textvariable=self.status,style='Muted.TLabel').grid(row=1,column=1,sticky='ew')
        self.cancel_button=ttk.Button(footer,text='Stop task',command=self.cancel.set,state='disabled');self.cancel_button.grid(row=0,column=2,rowspan=2,padx=(16,0))
        self.wrap_labels(root)
        root.bind('<MouseWheel>',self.scroll_panel_wheel,add='+')
        root.bind('<FocusIn>',self.reveal_focus,add='+')
        root.protocol('WM_DELETE_WINDOW',self.close)
        self.poll_timer=root.after(100,self.poll);self.activity_timer=root.after(500,self.update_activity)
        root.bind('<Destroy>',self.cleanup,add='+')
        self.sync_review_actions()
        if initial_job:self.refresh()

    def update_navigation(self,event=None):
        for page,button in self.nav_buttons.items():
            button.configure(style='Active.Nav.TButton' if page==self.tabs.select() else 'Nav.TButton')

    def update_short_filename(self,*args):
        text=self.filename.get()
        self.short_filename.set(text if len(text)<=42 else text[:26]+'…'+text[-12:])

    def fit_review_count(self):
        available=max(100,self.count_label.winfo_width())
        for size in range(24,11,-1):
            if tkfont.Font(family=UI_FONT,size=size).measure(self.review_count.get())<=available:
                self.count_label.configure(font=(UI_FONT,size));break

    def update_activity(self):
        if self.busy:
            seconds=int(time.monotonic()-self.progress.started)
            self.activity.set(f"{'Stopping safely' if self.cancel.is_set() else 'Processing'}  ·  {seconds//60:02d}:{seconds%60:02d}")
        else:self.activity.set('Ready')
        self.activity_timer=self.root.after(500,self.update_activity)

    def cleanup(self,event):
        if event.widget is self.root:
            for timer in (self.poll_timer,self.activity_timer,self.review_timer):
                if timer is None:continue
                try:self.root.after_cancel(timer)
                except tk.TclError:pass

    def reveal_focus(self,event):
        widget=event.widget
        while widget is not None:
            canvas=getattr(widget,'scroll_canvas',None)
            if canvas is not None:
                top=event.widget.winfo_rooty()-canvas.winfo_rooty()
                bottom=top+event.widget.winfo_height()
                offset=event.widget.winfo_rooty()-widget.winfo_rooty()
                if top<0:canvas.yview_moveto(max(0,offset-12)/max(1,widget.winfo_height()))
                elif bottom>canvas.winfo_height():canvas.yview_moveto(max(0,offset+event.widget.winfo_height()-canvas.winfo_height()+12)/max(1,widget.winfo_height()))
                return
            widget=widget.master

    def update_review_progress(self,read_counts=False):
        job=self.job.get()
        if job!=self.progress_job or read_counts:
            counts=workflow.feedback_counts(self.job_path())
            self.reviewed_count=sum(sum(c.values()) for c in counts.values());self.progress_job=job
        self.review_count.set(f'{self.reviewed_count:,} / {self.ready_total:,}')
        self.fit_review_count()
        self.review_progress.set(self.reviewed_count,self.ready_total)
        if getattr(self,'displayed_job',None)==Path(job).resolve():
            self.pair_heading.set(f'PAIR {self.current:,} OF {self.ready_total:,} READY')

    def sync_review_actions(self):
        enabled=bool(self.job.get()) and getattr(self,'displayed_job',None)==Path(self.job.get()).resolve()
        for b in self.review_actions:
            b.configure(state='normal' if enabled and (not self.busy or self.scan_mode) and not self.review_pending and time.monotonic()>=self.review_cooldown else 'disabled')

    def button(self,parent,label,command,style='TButton'):
        b=ttk.Button(parent,text=label,style=style,command=lambda:self.guarded(command));self.buttons.append(b);return b

    def scroll_panel(self,parent):
        """Preserve readable tables and reachable actions at smaller window sizes."""
        canvas=tk.Canvas(parent,background=COLORS['surface'],highlightthickness=0,width=1,height=1)
        scroll=ttk.Scrollbar(parent,orient='vertical',command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True)
        content=ttk.Frame(canvas,padding=15)
        window=canvas.create_window(0,0,window=content,anchor='nw')
        content.scroll_canvas=canvas
        def resize(event=None):
            width=max(1,canvas.winfo_width())
            height=max(canvas.winfo_height(),content.winfo_reqheight())
            canvas.itemconfigure(window,width=width)
            canvas.configure(scrollregion=(0,0,width,height))
        canvas.bind('<Configure>',resize);content.bind('<Configure>',resize)
        return content

    def scroll_panel_wheel(self,event):
        # Tables and text areas retain their own scrolling behavior.
        if isinstance(event.widget,(ttk.Treeview,tk.Text,ttk.Combobox)):return
        widget=event.widget
        while widget is not None:
            canvas=getattr(widget,'scroll_canvas',None)
            if canvas is not None:
                if canvas.yview()!=(0.0,1.0):canvas.yview_scroll(-1 if event.delta>0 else 1,'units')
                return 'break'
            widget=widget.master

    def layout_column(self,parent):
        """Let result panels shrink first, keeping actions visible on small screens."""
        parent.columnconfigure(0,weight=1)
        children=[(child,child.pack_info()) for child in parent.winfo_children()]
        for child,info in children:child.pack_forget()
        for row,(child,info) in enumerate(children):
            flexible=bool(info.get('expand'))
            sticky='nsew' if flexible else ('w' if isinstance(child,ttk.Button) else 'ew')
            child.grid(row=row,column=0,sticky=sticky,
                       padx=info.get('padx',0),pady=info.get('pady',0))
            parent.rowconfigure(row,weight=1 if flexible else 0)

    def wrap_labels(self,parent):
        """Wrap explanatory text to its visible width after window resizing."""
        for child in parent.winfo_children():
            if isinstance(child,ttk.Label) and child.cget('wraplength'):
                if child.winfo_manager()=='pack':child.pack_configure(fill='x')
                child.bind('<Configure>',lambda event: event.widget.configure(wraplength=max(80,event.width)))
            self.wrap_labels(child)

    def guarded(self,command):
        if self.review_pending:
            self.review_notice.set('Saving your decision… Please wait.');return
        try:command()
        except Exception as exc:self.status.set(str(exc));messagebox.showerror('Twin Finder',str(exc),parent=self.root)

    def diagnostics(self):
        """Exercise the bundled neural runtime and save a support report."""
        import tempfile
        output=Path(tempfile.gettempdir())/'TwinFinder-diagnostics.json'
        def task(progress):
            progress('Checking the bundled neural model…')
            result=neural_test();result['tk_ui_constructed']=True
            output.write_text(json.dumps(result,indent=2),encoding='utf-8')
            return result
        def done(result):
            self.status.set(f'Diagnostics passed. Report: {output}')
            messagebox.showinfo('Diagnostics passed',f"Neural dimension: {result['neural_dimension']}\nScore: {result['score']:.6f}\nReport: {output}",parent=self.root)
        self.run(task,done)

    def build_data(self):
        f=self.data_tab
        self.source=tk.StringVar();self.mapping={k:tk.StringVar() for k in core_fields()}
        self.max_pairs=tk.StringVar(value='10000');self.budget=tk.StringVar(value='3000000')
        ttk.Label(f,text='BIBLIOGRAPHIC DATA CLEANING',style='Kicker.TLabel').pack(anchor='w',pady=(12,14))
        wrap_label(f,text='Cleaner records.\nClearer decisions.',style='Hero.TLabel').pack(fill='x')
        wrap_label(f,text='Open a dataset. Review the first ready matches while AI continues working in the background.',style='Muted.TLabel').pack(fill='x',pady=(14,20))
        self.choose_button=self.button(f,'Choose your dataset  →',self.open_dataset_file,style='Primary.TButton');self.choose_button.pack(anchor='w')
        ttk.Label(f,text='CSV  /  JSONL  /  NDJSON     ·     Processed on this computer',style='Muted.TLabel').pack(anchor='w',pady=(10,22))
        wrap_label(f,textvariable=self.banner,style='Banner.TLabel').pack(fill='x',pady=(0,10))
        self.data_summary=tk.Text(f,height=5,wrap='word',font=(UI_FONT,10),bg=COLORS['card'],fg=COLORS['text'],relief='flat',borderwidth=0,padx=18,pady=16,spacing3=5,selectbackground=COLORS['selection'],selectforeground=COLORS['text'])
        self.data_summary.pack(fill='both',expand=True)
        self.set_text(self.data_summary,'01  Open a file\nStandard columns are detected automatically. Ambiguous columns need a quick confirmation.\n\n02  Review the evidence\nCompare two papers, see the AI signals, then accept, reject or skip. Your decisions are saved.\n\n03  Learn and export\nUse reviewed pairs to propose a classifier update. Export only consolidations you approved.\n\nLocal processing has no fixed upload cap. Disk space, processing time and candidate limits still apply.')
        self.layout_column(f)

    def recent_path(self):
        return recent_jobs_path()

    def update_recent_menu(self):
        self.recent_menu.delete(0,'end')
        try:entries=json.loads(self.recent_path().read_text(encoding='utf-8'))
        except (OSError,ValueError):entries=[]
        for entry in entries[:10]:
            self.recent_menu.add_command(label=entry['name'],command=lambda path=entry['path']:self.guarded(lambda:self.open_recent(path)))
        if not entries:self.recent_menu.add_command(label='No saved datasets yet',state='disabled')

    def remember_job(self):
        path=self.recent_path()
        try:entries=json.loads(path.read_text(encoding='utf-8'))
        except (OSError,ValueError):entries=[]
        job=str(self.job_path());entries=[e for e in entries if e['path']!=job]
        entries.insert(0,{'path':job,'name':self.filename.get()+' — '+Path(job).name})
        try:
            path.parent.mkdir(parents=True,exist_ok=True)
            temp=path.with_suffix('.tmp');temp.write_text(json.dumps(entries[:10],indent=2),encoding='utf-8');temp.replace(path)
        except OSError:return
        self.update_recent_menu()

    def open_recent(self,path):
        if self.busy:raise ValueError('Pause processing before opening another dataset.')
        if not Path(path).is_dir():raise ValueError('Saved working folder has moved or is no longer available.')
        self.job.set(path);self.first_shown=False;self.displayed_job=None;self.proposal=None
        self.refresh()

    def processing_limits(self):
        if self.busy:raise ValueError('Pause processing before changing settings for a new dataset.')
        from tkinter import simpledialog
        value=simpledialog.askinteger('Processing limits','Maximum review pairs for NEW datasets (existing jobs retain their limits):',initialvalue=int(self.max_pairs.get()),minvalue=50,maxvalue=100000,parent=self.root)
        if value:self.max_pairs.set(str(value))

    def confirm_mapping(self,columns,mapping):
        dialog=tk.Toplevel(self.root);dialog.title('Confirm bibliographic columns');dialog.transient(self.root)
        frame=ttk.Frame(dialog,padding=20);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='Some column names are ambiguous. Confirm them once.').grid(row=0,column=0,columnspan=2,pady=10)
        values={}
        for row,field in enumerate(core_fields(),1):
            ttk.Label(frame,text=field.title()+(' (required)' if field=='title' else ' (optional)')).grid(row=row,column=0,sticky='w',padx=8)
            values[field]=tk.StringVar(value=mapping[field] or '')
            ttk.Combobox(frame,textvariable=values[field],values=['']+columns,state='readonly',width=35).grid(row=row,column=1,pady=5)
        result=[]
        def accept():
            proposed={k:v.get() or None for k,v in values.items()}
            try:storage.validate_mapping(proposed,columns)
            except ValueError as exc:messagebox.showerror('Columns',str(exc),parent=dialog);return
            result.append(proposed);dialog.destroy()
        ttk.Button(frame,text='Start processing',style='Primary.TButton',command=accept).grid(row=5,column=0,columnspan=2,pady=12)
        dialog.grab_set();self.root.wait_window(dialog)
        return result[0] if result else None

    def open_dataset_file(self):
        if self.busy:raise ValueError('Pause the current dataset before opening another.')
        name=filedialog.askopenfilename(title='Open bibliographic dataset',filetypes=[('Bibliographic records','*.csv *.jsonl *.ndjson')])
        if not name:return
        columns=storage.peek_columns(name);mapping,ambiguous=progressive.detect_mapping(columns)
        if ambiguous:
            mapping=self.confirm_mapping(columns,mapping)
            if mapping is None:return
        parent=Path(name).parent/'TwinFinderJobs'
        job=parent/(Path(name).stem+'_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6])
        self.job.set(str(job));self.source.set(name);self.filename.set(Path(name).name)
        for k,v in mapping.items():self.mapping[k].set(v or '')
        self.first_shown=False;self.displayed_job=None;self.proposal=None
        self.remember_job()
        self.tabs.select(self.data_tab)
        self.start_scan(name,job,mapping)

    def start_scan(self,source,job,mapping):
        maximum=int(self.max_pairs.get());budget=int(self.budget.get())
        self.run(lambda progress:progressive.run(source,job,mapping,maximum,budget,progress,self.cancel),lambda result:self.refresh(),scanning=True)

    def resume_processing(self):
        job=self.job_path()
        if progressive.is_progressive(job):
            state=progressive.snapshot(job)
            if state['status']=='complete':self.refresh();return
            self.start_scan(state['source'],job,state['mapping'])
        elif (job/'records.sqlite').exists():
            self.run(lambda progress:workflow.prepare(job,progress=progress,cancel=self.cancel),lambda result:self.refresh())
        elif (job/'importing.sqlite').exists():
            db=storage.connect(job/'importing.sqlite')
            try:state=json.loads(db.execute("SELECT value FROM meta WHERE key='checkpoint'").fetchone()[0])
            finally:db.close()
            def task(progress):
                with storage.job_lock(job):storage.import_file(state['identity']['path'],job,state['identity']['mapping'],lambda n:progress(f'Imported {n:,} records'),self.cancel)
                return workflow.prepare(job,progress=progress,cancel=self.cancel)
            self.run(task,lambda result:self.refresh())
        else:raise ValueError('Open a dataset first.')

    def build_review(self):
        f=self.review_content
        self.pair_heading=tk.StringVar(value='YOUR REVIEW QUEUE')
        top=ttk.Frame(f);top.pack(fill='x',pady=(0,14))
        ttk.Label(top,textvariable=self.pair_heading,style='Kicker.TLabel').pack(side='left')
        self.button(top,'Next pair  →',self.next_pair,style='Quiet.TButton').pack(side='right')
        self.button(top,'←  Previous pair',self.previous_pair,style='Quiet.TButton').pack(side='right')
        prediction=Card(f,padding=16);prediction.pack(fill='x',pady=(0,16))
        prediction.body.columnconfigure(0,weight=1)
        self.verdict=tk.StringVar(value='Your first match will appear here')
        wrap_label(prediction.body,textvariable=self.verdict,style='CardTitle.TLabel').grid(row=0,column=0,sticky='ew')
        self.prediction_note=tk.StringVar(value='Open a dataset to start finding candidate pairs.')
        wrap_label(prediction.body,textvariable=self.prediction_note,style='CardMuted.TLabel').grid(row=1,column=0,sticky='ew',pady=(6,0))
        self.score_text=tk.StringVar(value='—')
        ttk.Label(prediction.body,textvariable=self.score_text,style='Score.TLabel').grid(row=0,column=1,sticky='e',padx=(20,0))
        ttk.Label(prediction.body,text='MODEL SCORE',style='CardMuted.TLabel',font=(UI_FONT,8,'bold')).grid(row=1,column=1,sticky='e',padx=(20,0))
        self.cards=ttk.Frame(f);self.cards.pack(fill='x',pady=(0,20))
        self.paper_cards=[];self.paper_values=[]
        for letter in ('A','B'):
            card=Card(self.cards);self.paper_cards.append(card)
            ttk.Label(card.body,text='PAPER '+letter,style='CardMuted.TLabel',font=(UI_FONT,9,'bold')).pack(anchor='w',pady=(0,12))
            values={k:tk.StringVar(value='Waiting for a match' if k=='title' else '—') for k in core_fields()}
            wrap_label(card.body,textvariable=values['title'],style='CardTitle.TLabel').pack(fill='x',pady=(0,16))
            for key in ('authors','venue','year'):
                row=ttk.Frame(card.body,style='Card.TFrame');row.pack(fill='x',pady=3);row.columnconfigure(1,weight=1)
                ttk.Label(row,text=key.title(),style='CardMuted.TLabel',width=8).grid(row=0,column=0,sticky='nw')
                wrap_label(row,textvariable=values[key],style='Card.TLabel').grid(row=0,column=1,sticky='ew')
            self.paper_values.append(values)
        self.cards.bind('<Configure>',self.arrange_cards)
        ttk.Label(f,text='FIELD SIMILARITY',style='Kicker.TLabel').pack(anchor='w',pady=(0,10))
        self.similarity_bars={}
        for key,label in [('title_edit','Title wording'),('author_overlap','Authors'),('venue_equal','Venue · exact match'),('year_equal','Year · exact match'),('title_semantic','Title meaning · AI')]:
            bar=SimilarityBar(f,label);bar.pack(fill='x',pady=5);self.similarity_bars[key]=bar
        wrap_label(f,text='N/A means a comparison is unavailable. These signals are not confidence percentages.',style='Muted.TLabel').pack(fill='x',pady=(6,16))
        self.explanation=tk.StringVar(value='AI suggests a match. Your review decides whether records may be consolidated.')
        wrap_label(f,textvariable=self.explanation,style='Muted.TLabel').pack(fill='x',pady=(0,12))
        self.details_button=ttk.Button(f,text='AI details and navigation  +',style='Quiet.TButton',command=self.toggle_details)
        self.details_button.pack(anchor='w',pady=(4,8))
        self.details=ttk.Frame(f)
        nav=ttk.Frame(self.details);nav.pack(fill='x',pady=(0,8))
        ttk.Label(nav,text='Pair').pack(side='left');self.pair_var=tk.StringVar(value='1')
        ttk.Entry(nav,textvariable=self.pair_var,width=6).pack(side='left',padx=6)
        self.button(nav,'Show pair',self.show_pair).pack(side='left')
        self.role=tk.StringVar(value='all')
        ttk.Combobox(nav,textvariable=self.role,values=['all','training','validation'],state='readonly',width=10).pack(side='left',padx=8)
        self.button(self.details,'Next uncertain unreviewed',self.uncertain).pack(anchor='w',pady=(0,10))
        self.review_info=tk.StringVar();wrap_label(self.details,textvariable=self.review_info,style='Muted.TLabel').pack(fill='x',pady=(0,8))
        self.record_tree=self.tree(self.details,[('field','Original field',130),('left','Paper A',320),('right','Paper B',320)],height=4)
        ttk.Label(self.details,text='Classifier evidence · logit contributions',style='Kicker.TLabel').pack(anchor='w',pady=(14,8))
        self.feature_tree=self.tree(self.details,[('feature','Feature',280),('value','Value',120),('contribution','Contribution',160)],height=5)
        self.formula=tk.StringVar();wrap_label(self.details,textvariable=self.formula,style='Muted.TLabel').pack(fill='x',pady=(10,0))
        # Fixed actions are outside the scrolling evidence panel.
        actions=ttk.Frame(self.review_tab,padding=(15,12,15,0))
        actions.pack(side='bottom',fill='x',before=self.review_tab.winfo_children()[0])
        actions.columnconfigure((0,1,2),weight=1,uniform='decisions')
        self.review_actions=[]
        for column,(label,decision) in enumerate([('Accept as duplicate','accept'),('Reject as distinct','reject'),('Skip / clear decision','skip')]):
            b=self.button(actions,label,lambda d=decision:self.save_review(d),style='Primary.TButton' if decision=='accept' else 'TButton')
            b.grid(row=0,column=column,sticky='ew',padx=(0,8) if column<2 else 0);self.review_actions.append(b)
        wrap_label(actions,text='Only accepted links permit consolidation. Every decision is saved and can be revised.',style='Muted.TLabel').grid(row=1,column=0,columnspan=3,sticky='ew',pady=(8,0))
        self.review_notice=tk.StringVar(value='Accept or reject to save and move to the next unreviewed pair.')
        wrap_label(actions,textvariable=self.review_notice,style='Muted.TLabel').grid(row=2,column=0,columnspan=3,sticky='ew',pady=(5,0))

    def arrange_cards(self,event=None):
        wide=self.cards.winfo_width()>=740*self.ui_scale
        self.cards.columnconfigure(0,weight=1,uniform='papers')
        self.cards.columnconfigure(1,weight=1 if wide else 0,uniform='papers' if wide else '')
        for i,card in enumerate(self.paper_cards):
            card.grid(row=0 if wide else i,column=i if wide else 0,sticky='nsew',padx=(0,14) if wide and i==0 else 0,pady=(0,12) if not wide and i==0 else 0)

    def toggle_details(self):
        if self.details.winfo_manager():self.details.pack_forget();self.details_button.configure(text='AI details and navigation  +')
        else:self.details.pack(fill='x',pady=(0,12));self.details_button.configure(text='AI details and navigation  −')

    def tree(self,parent,columns,height):
        frame=ttk.Frame(parent);frame.pack(fill='both',expand=True)
        tree=ttk.Treeview(frame,columns=[c[0] for c in columns],show='headings',height=height)
        for key,title,width in columns:
            tree.heading(key,text=title,anchor='w');tree.column(key,width=width,minwidth=60,anchor='e' if key in ('value','contribution') else 'w')
        tree.tag_configure('alternate',background=COLORS['subtle'])
        scroll=ttk.Scrollbar(frame,orient='vertical',command=tree.yview);tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y');tree.pack(side='left',fill='both',expand=True)
        horizontal=ttk.Scrollbar(parent,orient='horizontal',command=tree.xview);tree.configure(xscrollcommand=horizontal.set);horizontal.pack(fill='x')
        return tree

    def build_learning(self):
        f=self.learn_content
        ttk.Label(f,text='Train a proposed classifier update from your reviewed pairs',style='Sub.TLabel').pack(anchor='w')
        ttk.Label(f,text='The title-embedding model stays frozen. Training and validation use separate records. Repeated validation is monitoring, not an independent accuracy study.',wraplength=1030).pack(anchor='w',pady=7)
        self.counts=tk.StringVar(value='Review at least 8 accepted and 8 rejected training pairs, plus 4 accepted and 4 rejected validation pairs.')
        ttk.Label(f,textvariable=self.counts,wraplength=1030).pack(anchor='w',pady=7)
        actions=ttk.Frame(f);actions.pack(fill='x')
        self.button(actions,'Refresh label counts',self.refresh_counts).pack(side='left')
        self.train_button=self.button(actions,'Train and validate proposal',self.propose);self.train_button.pack(side='left',padx=8)
        self.button(actions,'Apply latest eligible proposal',self.activate).pack(side='left')
        action_buttons=actions.winfo_children()
        for button in action_buttons:button.pack_forget()
        def arrange_actions(event=None):
            wide=actions.winfo_width()>=sum(b.winfo_reqwidth()+8 for b in action_buttons)
            for i,button in enumerate(action_buttons):
                actions.columnconfigure(i,weight=1 if wide or i==0 else 0)
                button.grid(row=0 if wide else i,column=i if wide else 0,sticky='ew',padx=(0,8) if wide and i<2 else 0,pady=(0,8))
        actions.bind('<Configure>',arrange_actions);arrange_actions()
        proposal_frame=ttk.Frame(f);proposal_frame.pack(fill='both',expand=True,pady=12)
        self.learning_text=tk.Text(proposal_frame,height=13,wrap='word',font=(UI_FONT,10),bg=COLORS['subtle'],fg=COLORS['text'],relief='flat',borderwidth=0,highlightthickness=1,highlightbackground=COLORS['line'],highlightcolor=COLORS['accent'],padx=14,pady=12,spacing1=2,spacing3=4,selectbackground=COLORS['selection'],selectforeground=COLORS['text'])
        proposal_scroll=ttk.Scrollbar(proposal_frame,orient='vertical',command=self.learning_text.yview)
        self.learning_text.configure(yscrollcommand=proposal_scroll.set)
        proposal_scroll.pack(side='right',fill='y');self.learning_text.pack(side='left',fill='both',expand=True)
        rollback=ttk.Frame(f);rollback.pack(fill='x');ttk.Label(rollback,text='Restore model version').pack(side='left')
        self.version=tk.StringVar(value='0');ttk.Entry(rollback,textvariable=self.version,width=8).pack(side='left',padx=8)
        self.button(rollback,'Restore saved model',self.rollback).pack(side='left')
        ttk.Separator(f).pack(fill='x',pady=13)
        self.export_button=self.button(f,'Export cleaned data and audit ZIP',self.export,style='Primary.TButton');self.export_button.pack(anchor='w')
        ttk.Label(f,text='Export streams to disk. Original records, conflicting values, source mapping, reviews and the active classifier are included. Contradictory accept/reject groups block export.',wraplength=1030).pack(anchor='w',pady=8)

    def set_text(self,widget,text):
        widget.configure(state='normal');widget.delete('1.0','end');widget.insert('1.0',text);widget.configure(state='disabled')

    def job_path(self):
        if not self.job.get().strip():raise ValueError('Choose a working job folder first.')
        return Path(self.job.get()).resolve()

    def open_job(self):
        if self.busy:raise ValueError('Pause the current dataset before opening saved work.')
        folder=filedialog.askdirectory(title='Open saved Twin Finder working folder')
        if folder:
            self.job.set(folder);self.first_shown=False;self.displayed_job=None;self.proposal=None
            self.refresh()

    def refresh(self):
        job=self.job_path()
        if getattr(self,'refresh_job',None)!=job:
            self.refresh_job=job;self.proposal=None
            self.set_text(self.learning_text,'Train a proposal after sufficient accepted and rejected labels are available.')
            self.counts.set('Use Refresh label counts to inspect this dataset.')
            self.review_notice.set('Accept or reject to save and move to the next unreviewed pair.')
        if progressive.is_progressive(job):
            self.refresh_live();return
        if not (job/'records.sqlite').exists():
            if (job/'importing.sqlite').exists():
                db=storage.connect(job/'importing.sqlite')
                try:state=json.loads(db.execute("SELECT value FROM meta WHERE key='checkpoint'").fetchone()[0])
                finally:db.close()
                self.source.set(state['identity']['path'])
                for k,v in state['identity']['mapping'].items():self.mapping[k].set(v or '')
                self.status.set(f"Import paused at {state['count']:,} committed records. Click Resume processing.")
            return
        db,dataset=storage.open_dataset(job)
        try:
            self.filename.set(dataset['filename'])
            text=f"Dataset: {dataset['filename']}\nRecords: {len(dataset['rows']):,}\nOriginal size: {dataset['source_bytes']/1024**3:.3f} GiB\nWorking folder: {job}\n\n"
            if (job/'session.json').exists():
                session=storage.load_session(job,dataset);s=session['candidate_stats']
                self.active_mapping=session['mapping'];self.ready_total=len(session['pairs']);self.update_review_progress()
                text+=f"Candidate queue: {s['returned_pairs']:,}\nEligible pairs within processed budget: {s['eligible_pairs']:,}\nIterations: {s['iterations']:,} / {s['comparison_budget']:,}\nBudget reached: {s['budget_reached']}\nQueue truncated: {s['queue_truncated']}\nOversized token blocks skipped: {s['oversized_token_blocks']:,}\nAI ready: {session.get('ai_ready',False)}\n\nThis queue does not establish that all duplicates were discovered."
                if session.get('ai_ready'):
                    self.status.set(f"Ready · {len(dataset['rows']):,} records · {len(session['pairs']):,} pairs · AI model v{session['ai_model']['version']}")
                    self.proposal=session['proposals'][-1] if session['proposals'] else None
                    if self.proposal:self.display_proposal(self.proposal)
                    if self.ready_total and not self.first_shown:
                        self.display_pair(workflow.inspect(job,workflow.review_navigation(job)['next'] or 1));self.tabs.select(self.review_tab);self.first_shown=True
            else:text+='Next: prepare AI matching. You may stop safely and continue later.'
            self.set_text(self.data_summary,text)
        finally:db.close()

    def refresh_live(self):
        job=self.job_path();state=progressive.snapshot(job)
        self.filename.set(Path(state['source']).name)
        self.active_mapping=state['mapping'];self.ready_total=state['ready_pairs'];self.update_review_progress()
        complete=state['status']=='complete';ready=state['ready_pairs']
        label='Scan complete' if complete else ('Paused' if not self.busy else 'Scanning')
        if state['status']=='error':label='Processing stopped'
        limits=state['stats']['queue_truncated'] or state['stats']['budget_reached']
        self.banner.set(f"{label} · {state['records']:,} records · {ready:,} AI-scored pairs ready"+(' · candidate limit reached' if limits else ''))
        text=f"Dataset: {state['source']}\nSaved work: {job}\n\nRecords read: {state['records']:,}\nAI-scored pairs ready: {ready:,}\nState: {label}\nCandidate comparisons: {state['stats']['iterations']:,} / {state['stats']['comparison_budget']:,}\nQueue limit: {state['stats']['max_pairs']:,}\n\n"
        text+=('Processing has finished. Candidate discovery remains bounded; completion does not mean all true duplicates were found.' if complete else 'Results are partial. New pairs are appended as scanning continues; existing pair numbers and your reviews stay fixed.')
        if state['records']:
            db=storage.connect(job/'records.sqlite')
            try:preview=[row[0] for row in db.execute('SELECT title FROM records ORDER BY id LIMIT 5')]
            finally:db.close()
            text+='\n\nFirst records (preview):\n'+'\n'.join('• '+title[:180] for title in preview)
        if limits:text+='\nThe candidate queue or comparison budget was reached. Additional matches may be omitted.'
        if state.get('error'):text+='\n'+state['error']
        self.set_text(self.data_summary,text)
        if ready and not self.first_shown:
            self.display_pair(workflow.inspect(job,workflow.review_navigation(job)['next'] or 1));self.tabs.select(self.review_tab);self.first_shown=True
        if self.waiting_review and not self.review_pending:
            waiting_job,after,previous_total=self.waiting_review
            if waiting_job!=job:self.waiting_review=None
            elif ready>previous_total or complete:
                self.advance_review(job,after,'')
            elif not self.busy:
                self.review_notice.set('No other unreviewed pairs are ready. Resume processing to find more.')
        if self.scan_mode and self.busy:
            self.export_button.configure(state='disabled');self.train_button.configure(state='disabled')
        if complete and not self.busy:self.status.set('Ready. Review pairs, learn from your decisions, and export.')

    def display_pair(self,result):
        self.waiting_review=None
        self.displayed_job=self.job_path()
        self.current=result['pair_number'];self.pair_var.set(str(self.current));m=result['machine']
        self.present_pair(result)
        self.verdict.set(m['verdict'].title())
        old=result['latest_review'];self.review_info.set(f"Rows {result['source_rows'][0]} and {result['source_rows'][1]} · score > {m['threshold']:.4f} means duplicate · feedback role: {result['feedback_role']} · review: {old['decision'] if old else 'unreviewed'}")
        for tree in (self.record_tree,self.feature_tree):tree.delete(*tree.get_children())
        a,b=result['records']
        for index,field in enumerate(dict.fromkeys([*a,*b])):self.record_tree.insert('','end',values=(field,a.get(field,''),b.get(field,'')),tags=('alternate',) if index%2 else ())
        for index,field in enumerate(ai.FEATURES):self.feature_tree.insert('','end',values=(field,f"{m['feature_values'][field]:.4f}",f"{m['logit_contributions'][field]:+.4f}"),tags=('alternate',) if index%2 else ())
        self.formula.set(f"Intercept {m['intercept']:+.4f} + contributions = {m['logit']:.4f}; sigmoid gives {m['score']:.4f}. The score is not a calibrated probability.")

    def present_pair(self,result):
        m=result['machine'];values=m['feature_values']
        self.pair_heading.set(f"PAIR {result['pair_number']:,} OF {self.ready_total:,} READY")
        self.score_text.set(f"{m['score']:.4f}")
        old=result['latest_review'];decision=old['decision'] if old else 'unreviewed'
        self.prediction_note.set(f"AI model v{m['model_version']}  ·  Your decision: {decision}")
        for variables,record in zip(self.paper_values,result['records']):
            for key,var in variables.items():
                column=self.active_mapping.get(key)
                raw=record.get(column,'') if column else ''
                text='Not provided' if core.missing(raw) else str(raw)
                # Long values remain complete in the expandable original-field table.
                limit=700 if key=='title' else 400
                var.set(text if len(text)<=limit else text[:limit]+'… [full value in AI details]')
        availability={'title_edit':'title_available','author_overlap':'authors_available','venue_equal':'venue_available','year_equal':'year_available','title_semantic':'semantic_available'}
        for key,bar in self.similarity_bars.items():bar.set(values[key] if values[availability[key]] else None)
        self.explanation.set('AI combines title meaning, wording, author overlap and exact venue/year matches. Check both records before deciding. The model score is not a calibrated probability.')
        self.sync_review_actions()

    def show_pair(self):
        self.display_pair(workflow.inspect(self.job_path(),int(self.pair_var.get())))
        self.review_notice.set('Accept or reject to save and move to the next unreviewed pair.')
    def previous_pair(self):
        if self.current<=1:self.review_notice.set('This is the first pair.');return
        self.pair_var.set(str(self.current-1));self.show_pair()
    def next_pair(self):
        state=workflow.review_navigation(self.job_path(),self.current)
        if self.current>=state['total']:
            self.review_notice.set('This is the last ready pair.' if state['complete'] else 'More pairs may appear as processing continues.');return
        self.pair_var.set(str(self.current+1));self.show_pair()
    def save_review(self,decision):
        if self.review_pending or time.monotonic()<self.review_cooldown:return
        if getattr(self,'displayed_job',None)!=self.job_path():raise ValueError('Show a pair from this job before reviewing.')
        # Capture identity before starting the worker: a later UI update cannot
        # redirect this decision to a different pair or dataset.
        request=(self.job_path(),self.current,decision)
        self.review_pending=request;self.waiting_review=None
        self.review_notice.set('Saving your decision…');self.sync_review_actions()
        def save():
            try:
                workflow.review(*request)
                self.messages.put(('review_saved',request))
            except Exception as exc:self.messages.put(('review_error',(request,str(exc))))
        threading.Thread(target=save,daemon=True).start()

    def advance_review(self,job,after,prefix):
        state=workflow.review_navigation(job,after)
        self.ready_total=state['total'];self.reviewed_count=state['reviewed'];self.progress_job=str(job)
        self.update_review_progress()
        if state['next'] is not None:
            self.display_pair(workflow.inspect(job,state['next']))
            self.review_content.scroll_canvas.yview_moveto(0)
            message=f"Showing pair {state['next']:,} of {state['total']:,}."
        else:
            self.display_pair(workflow.inspect(job,after))
            if state['complete']:
                message='All candidate pairs reviewed.' if not state['remaining'] else 'No other unreviewed pairs. This skipped pair remains undecided.'
            else:
                self.waiting_review=(job,after,state['total'])
                message='Waiting for more pairs… They will appear automatically.' if self.busy else 'No other unreviewed pairs are ready. Resume processing to find more.'
        self.review_notice.set(prefix+message)

    def finish_review(self,kind,payload):
        self.review_pending=None
        if kind=='review_error':
            request,error=payload
            self.review_notice.set('Decision not saved. Stay on this pair and try again. '+error)
            self.status.set('Decision not saved. '+error)
        else:
            job,pair,decision=payload
            try:
                self.advance_review(job,pair,{'accept':'Accepted and saved. ','reject':'Rejected and saved. ','skip':'Skipped; left undecided. '}[decision])
            except Exception as exc:
                # Persistence already succeeded; a display failure must never be
                # reported as an unsaved decision or cause an automatic retry.
                self.review_notice.set('Decision saved, but the next pair could not load. Use Next pair. '+str(exc))
            # Prevent a rapid double-click from labelling the newly shown pair.
            self.review_cooldown=time.monotonic()+.35
            self.review_timer=self.root.after(360,self.sync_review_actions)
        self.sync_review_actions()
        if self.pending_close and not self.busy:self.root.destroy()
    def uncertain(self):
        job=self.job_path();role=self.role.get()
        def done(indices):
            if indices:self.display_pair(workflow.inspect(job,indices[0]))
            else:self.status.set('No unreviewed candidates remain for this role.')
        if self.scan_mode and self.busy:done(workflow.queue(job,role,True))
        else:self.run(lambda progress:workflow.queue(job,role,True),done)
    def refresh_counts(self):
        counts=workflow.feedback_counts(self.job_path());self.counts.set(' | '.join(f"{k}: {v['accept']} accepted, {v['reject']} rejected" for k,v in counts.items()))
    def propose(self):
        job=self.job_path();self.run(lambda progress:workflow.propose_update(job),self.display_proposal)
    def display_proposal(self,p):
        self.proposal_job=self.job_path()
        self.proposal=p;b=p['before'];a=p['after']
        self.set_text(self.learning_text,f"Proposal {p['id']} · candidate model v{p['model']['version']}\nTraining labels: {p['training_count']} · validation labels: {p['validation_count']}\n\nValidation agreement before / after\nPrecision: {b['precision']:.4f} / {a['precision']:.4f}\nRecall: {b['recall']:.4f} / {a['recall']:.4f}\nF1: {b['f1']:.4f} / {a['f1']:.4f}\n\nEligible to apply: {'YES' if p['eligible_to_apply'] else 'NO'}\n{p['gate']}\n\n{p['meaning']}")
    def activate(self):
        if self.proposal is None:raise ValueError('Train a proposal first.')
        if self.proposal_job!=self.job_path():raise ValueError('Load or train a proposal for the selected job first.')
        workflow.activate(self.job_path(),self.proposal['id']);self.refresh();self.status.set('Model activated. Existing candidate predictions now use the updated classifier.')
    def rollback(self):workflow.rollback(self.job_path(),int(self.version.get()));self.refresh()
    def export(self):
        job=self.job_path();name=filedialog.asksaveasfilename(title='Save cleaned data and audit',defaultextension='.zip',filetypes=[('Audit archive','*.zip')])
        if not name:return
        def task(progress):
            with storage.job_lock(job):return storage.export_cleaned(job,name,lambda n:progress(f'Exported through source row {n:,}'),self.cancel)
        self.run(task,lambda result:self.status.set(f"Saved {result['output_records']:,} records to {name}; originals and audit included."))

    def run(self,task,done,scanning=False):
        if self.busy:raise ValueError('Wait for the current task to finish or stop it.')
        self.busy=True;self.scan_mode=scanning;self.cancel.clear();self.done_callback=done
        self.input_states=[]
        def disable_inputs(widget):
            for child in widget.winfo_children():
                if isinstance(child,(ttk.Entry,ttk.Combobox)):
                    self.input_states.append((child,str(child.cget('state'))));child.configure(state='disabled')
                disable_inputs(child)
        if not scanning:disable_inputs(self.root)
        for b in self.buttons:b.configure(state='normal' if scanning else 'disabled')
        if scanning:
            for b in (self.open_button,self.choose_button,self.saved_button,self.resume_button,self.train_button,self.export_button):b.configure(state='disabled')
        self.sync_review_actions()
        self.cancel_button.configure(state='normal');self.progress.start();self.status.set('Starting local processing…')
        def target():
            try:self.messages.put(('done',task(lambda text:self.messages.put(('progress',text)))))
            except storage.Cancelled as exc:self.messages.put(('cancelled',str(exc)))
            except Exception as exc:self.messages.put(('error',str(exc)))
        threading.Thread(target=target,daemon=True).start()
    def poll(self):
        try:
            while True:
                kind,payload=self.messages.get_nowait()
                if kind in ('review_saved','review_error'):
                    self.finish_review(kind,payload)
                    if self.pending_close and not self.busy:return
                    continue
                if kind=='progress':self.status.set(payload);continue
                self.busy=False;self.progress.stop();self.cancel_button.configure(state='disabled')
                for b in self.buttons:b.configure(state='normal')
                for widget,state in self.input_states:widget.configure(state=state)
                if kind=='done':self.status.set('Task completed.');self.guarded(lambda:self.done_callback(payload))
                else:
                    self.status.set(payload)
                    if self.scan_mode:self.guarded(self.refresh)
                if kind=='error':messagebox.showerror('Task could not finish',payload,parent=self.root)
                self.sync_review_actions()
                if self.pending_close and not self.review_pending:self.root.destroy();return
        except queue.Empty:pass
        if self.busy and self.scan_mode and time.monotonic()-self.last_snapshot>1:
            self.last_snapshot=time.monotonic()
            try:self.refresh_live()
            except (sqlite3.OperationalError,TypeError,FileNotFoundError):pass
        self.poll_timer=self.root.after(100,self.poll)
    def close(self):
        if self.review_pending and not self.busy:
            self.pending_close=True;self.review_notice.set('Finishing the save before closing…');return
        if self.busy:
            if messagebox.askyesno('Stop and close','Stop the current task safely and close when it reaches a checkpoint?',parent=self.root):self.cancel.set();self.pending_close=True
        else:self.root.destroy()


def core_fields():
    return ('title','authors','venue','year')


def neural_test():
    import numpy as np
    encoder=ai.Encoder();v=encoder.encode(['graph indexing','graph indexing'])
    a={'title':'graph indexing','authors':'Alice Chen','venue':'SIGMOD','year':'2020'}
    result=ai.explain(ai.features(a,a,v[0],v[1]),ai.load_base())
    # CPU kernels can differ by a few float32 rounding units within one batch.
    # Check finiteness, normalization and agreement with an explicit tolerance.
    delta=float(np.max(np.abs(v[0]-v[1])))
    assert np.isfinite(v).all() and np.allclose(np.linalg.norm(v,axis=1),1,atol=1e-5)
    assert delta<=1e-6 and np.isfinite(result['score']) and 0<=result['score']<=1
    return {'status':'passed','neural_dimension':v.shape[1],'score':result['score'],
            'duplicate_embedding_max_delta':delta,'duplicate_embedding_tolerance':1e-6}

def self_test(output):
    result=neural_test()
    root=create_root();root.withdraw();app=App(root);root.update();root.destroy()
    result['tk_ui_constructed']=True
    Path(output).write_text(json.dumps(result,indent=2),encoding='utf-8')

def main():
    p=argparse.ArgumentParser();p.add_argument('--job',type=Path);p.add_argument('--self-test',type=Path);a=p.parse_args()
    if a.self_test:self_test(a.self_test);return
    root=create_root();App(root,a.job);root.mainloop()

if __name__=='__main__':
    try:main()
    except Exception:
        import sys
        if '--self-test' in sys.argv:
            output=Path(sys.argv[sys.argv.index('--self-test')+1])
            output.write_text(json.dumps({'status':'failed','traceback':traceback.format_exc()},indent=2))
            sys.exit(1)
        raise
