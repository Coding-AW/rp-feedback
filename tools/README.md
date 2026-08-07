# tools/ — OPTIONAL. Nothing depends on this folder.

Convenience only: running a notebook from the PC instead of the browser, and setting up
password-free access. **Parked while the measurement itself is being sorted out** — it works,
but it is one more thing to be wrong, and none of it is needed to use the project.

Everything can be done the plain way:

| Task | Plain way |
|---|---|
| Run a test | Open it in the board's Jupyter page and press play |
| Find the signal | On the board: `sudo python3 find_signal.py` |
| Check the system | On the board: `sudo python3 check_system.py` |
| Build | In Vivado's Tcl console: `source .../build_project.tcl` |

## If you do want it

| File | What it does |
|---|---|
| `setup_board_access.ps1` | Run once. SSH key, so no more passwords. Also adds the board's own name to its `/etc/hosts`, which is what causes the `sudo: unable to resolve host` delay, and sets its clock |
| `run_on_board.ps1` | Runs a notebook on the board from the PC and drops the log and plots into `results\` |
| `nb_to_script.py` | Notebook to plain script. Used by the above |
| `backup.ps1` | Copies the whole project to a USB stick, dated. See `../BACKUP.md` |
| `verify_rtl.py` | **Not optional in spirit.** Checks the Verilog for names that do not line up — a port connected that does not exist, a signal assigned that was never declared. Catches in one second what synthesis takes ninety to report. Run after any RTL edit: `python3 tools/verify_rtl.py` |
| `verify_notebooks.py` | **Not optional in spirit.** Checks every call in every notebook against the function it calls. Run it after editing the measurement helpers: `python3 tools/verify_notebooks.py jupyter_notebooks/acquisition/*.ipynb` |

## One thing worth knowing either way

**The notebooks on the board and the notebooks in this project are separate copies.** The
browser edits the board's; this folder holds the master. They drift apart, and when they do the
board runs old code while you read new code — which happened on 2026-07-29 and produced a
confusing hour.

`run_on_board.ps1` avoids it by copying the master across on every run. If you work in the
browser instead, copy them across yourself after any change:

```
scp "jupyter_notebooks\acquisition\*.ipynb" root@rp-f007f7.local:/root/jupyter/RedPitaya/
```
