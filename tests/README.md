# Tests

- `rtl/`: focused XSim/Yosys regressions using the project-owned HDL in
  `fpga/`;
- `python/`: notebook static checks and an end-to-end mock runner;
- `fixtures/`: fake hardware and known-answer data.

Run the fast supported suite from the repository root:

```powershell
.\project.ps1 test
```

The mock runner can also exercise the coil-characterisation notebook across its
scenario matrix:

```powershell
python tests/python/audit_notebooks.py
python tests/python/run_notebook_mocks.py all
```

RTL scripts that require Vivado 2020.1 are intentionally separate from the fast
test command. Physical-board acceptance additionally requires deployment,
`project.ps1 check`, and the numbered notebooks.
