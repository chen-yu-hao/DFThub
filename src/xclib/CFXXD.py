from .numint_tools import *
import numpy as np
import numpy
def int_xc_noHF(mf_hf,ni,rho,weight,ee):
    weight = mf_hf.grids.weights
    xa = xf(rho[0])
    xb = xf(rho[1])
    vx_a = vxf(rho[0],wx=2.50)
    ux_a = uxf(xa,gamma=0.004)
    w_a = wf(rho[0])
    ex_a = exf(rho[0])
    vx_b = vxf(rho[1],wx=2.50)
    ux_b = uxf(xb,gamma=0.004)
    w_b = wf(rho[1])
    ex_b = exf(rho[1])
    for i in range(4):
        for j in range(4-i):
            for k in range(6-i-j):
                ee.append(E_ijk(rho[0],ex_a,vx_a,ux_a,w_a,i,j,k,weight)+E_ijk(rho[1],ex_b,vx_b,ux_b,w_b,i,j,k,weight))
    # LSDA = ni.eval_xc(",PW_mod",rho[:,0],spin=1)[0]
    LSDA = ni.eval_xc(',PW_mod',rho[:,0],spin=1)[0]
    for i in range(9):
        ee.append((rho[0,0]*LSDA*w_a**i+rho[1,0]*LSDA*w_b**i).dot(weight))
    PBE = ni.eval_xc(",PBE",rho[:,:4],spin=1)[0]
    for i in range(9):
        ee.append((rho[0,0]*(PBE-LSDA)*w_a**i+rho[1,0]*(PBE-LSDA)*w_b**i).dot(weight))
    rho_a,rho_b = rho[:,0]
    UEGab = LSDA
    UEGa = ni.eval_xc(',PW_mod',(rho_a,np.zeros_like(rho_b)),spin=1)[0]
    UEGb = ni.eval_xc(',PW_mod',(rho_b,np.zeros_like(rho_a)),spin=1)[0]
    zeta = zetf(rho[0])
    zetb = zetf(rho[1])
    zetab = zeta+zetb
    h_anti = h_function(xa**2+xb**2,zetab)
    ha = h_function(xa**2,zeta,alpha=0.00515088)
    hb = h_function(xb**2,zetb,alpha=0.00515088)
    Da = Dsigma(rho[0])
    Db = Dsigma(rho[1])
    for value in h_anti:
        ee.append(((UEGab*(rho_a+rho_b)-UEGa*rho_a-UEGb*rho_b)*value).dot(weight))
    for a,b in zip(ha,hb):
        ee.append((UEGa*rho_a*a*Da+UEGb*rho_b*b*Db).dot(weight))
    xab = np.sqrt((xa**2+xb**2))
    ucab = uxf(xab,0.0031)
    for i in range(5):
        ee.append(((UEGab*(rho_a+rho_b)-UEGa*rho_a-UEGb*rho_b)*ucab**i).dot(weight))
    ua = uxf(xa,0.06)
    ub = uxf(xb,0.06)
    for i in range(5):
        ee.append((UEGa*rho_a*ua**i*Da+UEGb*rho_b*ub**i*Db).dot(weight))
    return ee
def int_xc(mf_hf,ni,rho,weight,ee):
    # rho = np.float128(rho)
    weight = mf_hf.grids.weights
    # rho_0 = rho[:,0,]
    rho = np.where(np.abs(rho)<1e-16,1e-16,rho)
    xa = xf(rho[0])
    xb = xf(rho[1])
    vx_a = vxf(rho[0],wx=2.50)
    ux_a = uxf(xa,gamma=0.004)
    w_a = wf(rho[0])
    ex_a = exf(rho[0])
    vx_b = vxf(rho[1],wx=2.50)
    ux_b = uxf(xb,gamma=0.004)
    w_b = wf(rho[1])
    ex_b = exf(rho[1])
    # ee = []
    # ee.append(dft_energy_without_xc(mf_hf))
    for i in range(4):
        for j in range(4-i):
            for k in range(6-i-j):
                ee.append(E_ijk(rho[0],ex_a,vx_a,ux_a,w_a,i,j,k,weight)+E_ijk(rho[1],ex_b,vx_b,ux_b,w_b,i,j,k,weight))
                # print(E_ijk(rho[0],ex_a,vx_a,ux_a,w_a,i,j,k,weight)+E_ijk(rho[1],ex_b,vx_b,ux_b,w_b,i,j,k,weight),end="  ")
            # print(i,j,k)
    w_total = wf_total(rho)
    LSDA = ni.eval_xc(',PW_mod',rho[:,0],spin=1)[0]
    for i in range(9):
        ee.append((rho[:,0].sum(axis=0)*(LSDA*w_total**i)).dot(weight))
    PBE = ni.eval_xc(",PBE",rho[:,:4],spin=1)[0]
    for i in range(9):
        ee.append((rho[:,0].sum(axis=0)*((PBE-LSDA)*w_total**i)).dot(weight))
    rho_a,rho_b = rho[:,0]
    # rho_a[rho_a < 1e-12] = 0
    # rho_b[rho_b < 1e-12] = 0
    UEGab = LSDA
    UEGa = ni.eval_xc(',PW_mod',(rho_a,np.zeros_like(rho_b)),spin=1)[0]
    UEGb = ni.eval_xc(',PW_mod',(rho_b,np.zeros_like(rho_a)),spin=1)[0]
    # UEGb = ni.eval_xc(',PW_mod',(rho_b,np.zeros_like(rho_a)),spin=1)[0]
    # print((UEGab*(rho_a+rho_b)-UEGa*rho_a-UEGb*rho_b).dot(weight))

    zeta = zetf(rho[0])
    zetb = zetf(rho[1])
    zetab = zeta+zetb
    h_anti = h_function(xa**2+xb**2,zetab)
    ha = h_function(xa**2,zeta,alpha=0.00515088)
    hb = h_function(xb**2,zetb,alpha=0.00515088)

    Da = Dsigma(rho[0])
    Db = Dsigma(rho[1])
    
    for value in h_anti:
        # print(value.shape)
        ee.append(((UEGab*(rho_a+rho_b)-UEGa*rho_a-UEGb*rho_b)*value).dot(weight))

    for a,b in zip(ha,hb):
        # print(value.shape)
        ee.append((UEGa*rho_a*a*Da+UEGb*rho_b*b*Db).dot(weight))


    xab = np.sqrt((xa**2+xb**2))
    ucab = uxf(xab,0.0031)
    for i in range(5):
        ee.append(((UEGab*(rho_a+rho_b)-UEGa*rho_a-UEGb*rho_b)*ucab**i).dot(weight))
    
    
    ua = uxf(xa,0.06)
    ub = uxf(xb,0.06)

    for i in range(5):
        ee.append((UEGa*rho_a*ua**i*Da+UEGb*rho_b*ub**i*Db).dot(weight))
    # ee.append(ni.eval_xc('HF',(rho_a,rho_b),spin=1)[0].dot(weight))
    mf_hf.xc = 'hf'
    ee.append(mf_hf.get_veff().exc)
    mf_hf.xc = 'CF22D'
    # for i in range()
    return ee


def CF22D_nxc_rks(mf_hf):
    ni = mf_hf._numint
    rho = cache_xc_kernel1(ni,mf_hf.mol,mf_hf.grids,mf_hf.make_rdm1(),max_memory=mf_hf.max_memory)
    print("successfully calculated Rhos")
    # rho = np.array([rho/2,rho/2])
    weight = mf_hf.grids.weights
    # E0 baseline straight from the wavefunction: kinetic + e-nuc (e1) + Hartree
    # (coul) + nuclear repulsion (nuc) = total energy minus XC. Taken from the
    # converged SCF summary (captured before int_xc, which leaves mf.xc='CF22D'),
    # so it no longer depends on the hardcoded reference params in energy_xc().
    ss = mf_hf.scf_summary
    e0 = ss["e1"] + ss["coul"] + ss["nuc"]
    ee = [0.0]
    ee = int_xc(mf_hf,ni,rho,weight,ee)
    ee[0] = e0
    return ee
def cache_xc_kernel1(ni, mol, grids, dm, spin=1, max_memory=2000):
    '''Compute the 0th order density, Vxc and fxc.  They can be used in TDDFT,
    DFT hessian module etc. Note dm the zeroth order density matrix must be a
    hermitian matrix.
    '''
    ao_deriv = 2
    xctype = 'MGGA'
    hermi = 1
    make_rho, nset, nao = ni._gen_rho_evaluator(mol, dm, hermi, True, grids)
    if dm[0].ndim == 1:  # RKS
        rho = []
        for ao, mask, weight, coords \
                in ni.block_loop(mol, grids, nao, ao_deriv, max_memory=max_memory):
            # print(ao.dtype)
            rho.append(make_rho(0, ao, mask, xctype))
        rho = numpy.hstack(rho)
        if spin == 1:  # RKS with nr_rks_fxc_st
            rho *= .5
            rho = numpy.repeat(rho[numpy.newaxis], 2, axis=0)
    else:  # UKS
        assert dm[0].ndim == 2
        assert spin == 1
        rhoa = []
        rhob = []
        for ao, mask, weight, coords \
                in ni.block_loop(mol, grids, nao, ao_deriv, max_memory):
            rhoa.append(make_rho(0, ao, mask, xctype))
            rhob.append(make_rho(1, ao, mask, xctype))
        rho = numpy.array([numpy.hstack(rhoa), numpy.hstack(rhob)])
    # vxc, fxc = ni.eval_xc_eff(xc_code, rho, deriv=2, xctype=xctype, spin=spin)[1:3]
    return rho
def CF22D_nxc(mf_hf):
    ni = mf_hf._numint
    rho = cache_xc_kernel1(ni,mf_hf.mol,mf_hf.grids,mf_hf.make_rdm1(),max_memory=mf_hf.max_memory)
    weight = mf_hf.grids.weights
    print("successfully calculated Rhos")
    # E0 baseline straight from the wavefunction (e1 + coul + nuc = e_tot - XC),
    # taken from the converged SCF summary before int_xc; independent of the
    # hardcoded reference params in energy_xc(). See CF22D_nxc_rks for details.
    ss = mf_hf.scf_summary
    e0 = ss["e1"] + ss["coul"] + ss["nuc"]
    ee = [0.0]
    ee = int_xc(mf_hf,ni,rho,weight,ee)
    ee[0] = e0
    return ee


def energy_xc(ee):
    params = np.array([   
        0.24416116,  -0.389728151, -1.829675858, 1.396044771, 2.315047133, 0.397552547, # a000-a005
        1.082144406, -7.894560034, -3.656253030, 2.574496508, 4.031038406, # a010-a014
        -3.931389433,  0.333519075, -3.032270318, 3.673752289, # a020-a023
        3.005997956, -6.463733874, -4.596755225, # a030-a032
        0.964839180,  0.363791944,  1.646506623, -3.504641550, -3.922228074, # a100-a104
        0.843718076, 10.779373313,  2.293612669, 7.088363286, # a110-a113
        2.598770741, -0.088522116, 7.180809030, # a120-a122
        -1.017514009, 1.735020310, 3.499241561, 0.922224945, #  a200-a203
        -2.212903920, 0.243080429, 17.306321840,  # a210-a212
        0.311402396, -3.257126009, -3.372399742, # a300-a302
        0.873863376,  0.078066142,  6.576550257, -1.126030147, -3.244797887, -2.186090839,
        -3.489135041,  3.090689716,  3.866592474,
        0.828203832, -2.518707202, 10.436806314,  3.588267084, -5.789404145,  3.353560215,
        -2.432384384, -1.147183331,  2.991316045,
         0.462806])
    return np.sum(np.array(np.append(ee[:58],ee[-1]))*params)

def dft_energy_without_xc(mf, dm=None):
    """
    计算 DFT 的 E_without_XC = Tr[h_core D] + E_Coul + E_nuc
    并返回各分量与总能量。

    参数
    ----
    mf : pyscf.dft.RKS/UKS/GKS（或相容的 SCF 对象）
    dm : 可选，自旋密度矩阵
         - RKS/GKS: (norb, norb)
         - UKS: (2, norb, norb)

    返回
    ----
    dict:
        {
          'e1_hcore':  Tr[h_core D]        (电子一体项：动能+核吸引),
          'ecoul'   :  电子-电子库仑能,
          'e_nuc'   :  核-核斥能,
          'exc'     :  交换-相关能（若可得）,
          'e_tot'   :  PySCF 报告的总能量,
          'e_without_xc': e1_hcore + ecoul + e_nuc
        }
    """
    mol = mf.mol
    if dm is None:
        dm = mf.make_rdm1()

    # 统一计算 Tr[h_core D]，兼容 RKS/GKS（单矩阵）与 UKS（双自旋）
    h1e = mf.get_hcore()
    veff = mf.get_veff(mf.mol, dm)
    if not (isinstance(dm, np.ndarray) and dm.ndim == 2):
        dm = dm[0] + dm[1]
    e_nuc = mol.energy_nuc()

    # 拿 veff，并优先用标签提供的 ecoul/exc
    exc   = getattr(veff, 'exc',   None)
    ecoul = getattr(veff, 'ecoul', None)
    e1 = np.einsum('ij,ji->', h1e, dm).real
    # 兜底：从 energy_elec 拿到 e1 与 (ecoul+exc)，再用 exc 推回 ecoul
    # 对 DFT：mf.energy_elec(dm=..., h1e=..., vhf=veff) 返回 (e1, ecoul+exc)
    e1_check, e_coul_plus_xc = mf.energy_elec(dm=dm, h1e=h1e, vhf=veff)
    # 用 e1_check sanity check（允许微小积分/数值差）
    # 推回 ecoul
    if ecoul is None and exc is not None:
        ecoul = float(e_coul_plus_xc - exc)

    # 再兜底一次：有些版本把 exc 只放在 scf_summary
    if exc is None and hasattr(mf, 'scf_summary'):
        exc = mf.scf_summary.get('exc', None)

    if ecoul is None:
        raise RuntimeError("无法获得库仑能 ecoul（veff 无标签且无法从 energy_elec/Exc 推回）。")

    e_without_xc = float(e1 + ecoul + e_nuc)

    return e_without_xc
    
