import os
# from CFXXD_cal import *
from pyscf import gto, scf, lib, dft
import numpy as np
from xclib.numint_tools import *
from xclib.CFXXD import *
from xclib.pyscf_io import *
from pyscf import gto, scf, lib
from mokit.lib.fch2py import fch2py
from mokit.lib.ortho import check_orthonormal

def KS_fromfch(name,n=24,grids_level=6,memory=20000,verbose=0):
    with open(f"{name}.calculating", "w")as f:
        f.write("caling")
    # p = {}
    with open(f"{name}.py","r") as f:
        strs = f.read().replace("scf.UHF","dft.UKS").replace("scf.RHF","dft.RKS").replace("mf.max_memory = 4000",f"mf.max_memory = {memory}").replace("mf.max_cycle = 1",f"mf.max_cycle = 1\nmf.grids.level = {grids_level}")
    # exec(strs.split("\n\n")[0],globals())
    exec(strs.split("\n\n")[1],globals())
    lib.num_threads(n)
    exec(strs.split("\n\n")[2],globals())
    exec(strs.split("\n\n")[3],globals())
    mol.verbose = verbose
    # mol.max_memory = memory
    exec(strs.split("\n\n")[4],globals())
    mf.xc="CF22D,CF22D"
    mf.grids.level = grids_level
    exec(strs.split("\n\n")[5],globals())
    exec(strs.split("\n\n")[6],globals())
    dm = mf.make_rdm1()
    mf.max_cycle = 10
    print(mf.kernel(dm0=dm))
    if mol.spin==0:
        save_mf_uks(mf,f"{name}-RKS.pychk")
        exc = CF22D_nxc_rks(mf)
        np.savetxt(f"{name}-RKS.txt",exc)
        print(f"E0 = {exc[0]}")
    else:
        save_mf_uks(mf,f"{name}.pychk")
        exc = CF22D_nxc(mf)
        np.savetxt(f"{name}.txt",exc)
        print(f"E0 = {exc[0]}")

    # mf_hf = dft.UKS(mf.mo5)
    # mf_hf.mo_coeff =mf.mo_coeff
    # dm = mf_hf.make_rdm1()
    # # mf.max_cycle = 10
    # mf_hf.kernel(dm0=dm)
def KS(name,n=24,grids_level=6,memory=20000,verbose=0):
    with open(f"{name}.calculating", "w")as f:
        f.write("caling")
    # p = {}
    with open(f"{name}.py","r") as f:
        strs = f.read().replace("scf.UHF","dft.UKS").replace("scf.RHF","dft.RKS").replace("mf.max_memory = 4000",f"mf.max_memory = {memory}").replace("mf.max_cycle = 1",f"mf.max_cycle = 1000\nmf.grids.level = {grids_level}\nmf.xc='CF22D,CF22D'")
    # exec(strs.split("\n\n")[0],globals())
    exec(strs.split("\n\n")[1],globals())
    lib.num_threads(n)
    exec(strs.split("\n\n")[2],globals())
    exec(strs.split("\n\n")[3],globals())
    mol.verbose = verbose
    # mol.max_memory = memory
    exec(strs.split("\n\n")[4],globals())
    # mf = dft.
    
    
    # exec(strs.split("\n\n")[5],globals())
    # exec(strs.split("\n\n")[6],globals())
    # dm = mf.make_rdm1()
    # mf.max_cycle = 10
    # print(mf.kernel(dm0=dm))
    if mol.spin==0:
        save_mf_uks(mf,f"{name}-RKS.pychk")
        exc = CF22D_nxc_rks(mf)
        np.savetxt(f"{name}-RKS.txt",exc)
        print(f"E0 = {exc[0]}")
    else:
        save_mf_uks(mf,f"{name}.pychk")
        exc = CF22D_nxc(mf)
        np.savetxt(f"{name}.txt",exc)
        print(f"E0 = {exc[0]}")

    # mf_hf = dft.UKS(mf.mo5)
    # mf_hf.mo_coeff =mf.mo_coeff
    # dm = mf_hf.make_rdm1()
    # # mf.max_cycle = 10
    # mf_hf.kernel(dm0=dm)
