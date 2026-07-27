Twin Finder

Twin Finder is a desktop app I built to find duplicate records in bibliographic data — papers that are really the same work but appear twice with small differences (a changed title, reordered authors, a different venue). It ranks the pairs most likely to be duplicates, shows the evidence behind each match, and lets you accept or reject them yourself. It's the "human-in-the-loop" idea: the app suggests, you decide.

Download and run

Go to the Releases page and download TwinFinder.exe. Double-click it — there's nothing to install, it just runs.

The first time you open it, Windows may show a "Windows protected your PC" message because the app isn't signed. Click More info → Run anyway. This is normal for small apps like this one.

How to use it
Click Open a file… and choose a CSV or JSON file of records (or click Try sample data to test it).
Match your columns to Title, Authors, Venue, and Year — it usually guesses these for you.
Review each suggested pair. You'll see how similar the titles, authors, venue, and year are, and a short explanation of why the app thinks they're a match (or not).
Click Accept, Reject, or Skip on each pair.
When you're done, export your decisions as a JSON file.

Files can be any size ,large ones are read from disk in pieces, so it doesn't matter if the file is bigger than your computer's memory.

Running from the source code

If you'd rather run it from the Python source instead of the exe:

pip install -r requirements-desktop.txt
python twin_finder_desktop.py

You'll need Python 3.10 or newer. The main app is in twin_finder_desktop.py and the part that reads files and finds the candidate pairs is in scalable_processing.py.