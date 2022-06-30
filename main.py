'''
   Copyright 2022 Maksim Trushin  PET-Technology Podolsk
   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at
       http://www.apache.org/licenses/LICENSE-2.0
   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.
'''

import tkinter as tk

from dcm_magic import *

def clicked():
    name = txt.get("1.0","end-1c")
    shamanstvo(name)
    lbl1.configure(text = "SUCCES!!!!!!!")


window = tk.Tk()
window.title("UNPACK COMPRESSED DCM INTO SINGLE DCMs")
window.geometry('420x100')
lbl = tk.Label(window, text = 'ENTER FILENAME OF COMPRESSED MRI SERIES',)
lbl.grid(row=0, )
txt = tk.Text(window, width = 50, height=1)
txt.grid(row=1, )#column=0)
lbl1 = tk.Label(window,)
btn = tk.Button(window, text='UNCOMPRESS', command = clicked)
btn.grid(row=3,)# column=0)

lbl1.grid(row=4, )
window.mainloop()