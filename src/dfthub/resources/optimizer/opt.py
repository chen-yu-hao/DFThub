import json
import math
from types import SimpleNamespace

import numpy as np
from scipy.optimize import minimize
from dataset import CFXXD_Train_Data_Set

database2 = {
    # 'CF22D_dimer': ['Water_ccpol_ref'],
    # 'CF22D_trimer': ['Water_scan_ref'],
    'BH76': ['BH76RC_ref', 'DBH24_ref'],
    'W4-11': ['BDE99nonMR_ref','BDE99MR_ref',  'HAT707nonMR_ref',  'HAT707MR_ref', 'ISOMERIZATION20_ref', 'SN13_ref', 'TAE140MR_ref', 'TAE140nonMR_ref'],
    'Alk44': ['AlkAtom19_ref', 'AlkIsomer11_ref', 'AlkIsod14_ref'],
    'SW49': ['SW49Rel345_ref', 'SW49Bind345_ref', 'SW49Rel6_ref', 'SW49Bind6_ref'],
    'H2O20Bind4': ['H2O20Bind4_ref', 'H2O20Rel4_ref'], 'H2O20Bind10': ['H2O20Bind10_ref', 'H2O20Rel10_ref'],
    'Platonic24': ['PlatonicTAE6_ref', 'PlatonicIG6_ref', 'PlatonicID6_ref', 'PlatonicHD6_ref'],
    'CEPX33': ['PX13_ref', 'CE20_ref'], 'WCPT27': ['WCPT27_ref', 'WCPT6_ref'], 'A21x12': ['A21x12_ref'],
    'A24': ['A24_ref'], 'Bauza30': ['Bauza30_ref'], 'Butanediol65': ['Butanediol65_ref'],
    'BzDC215': ['BzDC215_ref'], 'CT20': ['CT20_ref'], 'DIE60': ['DIE60_ref'], 'DS14': ['DS14_ref'],
    'EIE22': ['EIE22_ref'], 'FmH2O10': ['FmH2O10_ref'], 'ACONF': ['ACONF_ref'], 'CYCONF': ['CYCONF_ref'],
    'G21EA': ['G21EA_ref'], 'G21IP': ['G21IP_ref'], 'NBPRC': ['NBPRC_ref'], 'WATER27': ['WATER27_ref'],
    'H2O6Bind8': ['H2O6Bind8_ref'], 'HB15': ['HB15_ref'], 'HW30': ['HW30_ref'], 'HW6Cl': ['HW6Cl_ref'],
    'HW6F': ['HW6F_ref'], 'NC15': ['NC15_ref'], 'Pentane14': ['Pentane14_ref'],
    'Shields38': ['Shields38_ref'], 'TA13': ['TA13_ref'], 'BHPERI26': ['BHPERI26_ref'],
    'CR20': ['CR20_ref'], 'CRBH20': ['CRBH20_ref'], 'AlkBind12': ['AlkBind12_ref'], 'HB49': ['HB49_ref'],
    'Ionic43': ['Ionic43_ref'], 'H2O16Rel5': ['H2O16Rel5_ref'], 'BSR36': ['BSR36_ref'],
    'HNBrBDE18': ['HNBrBDE18_ref'], 'SR-MGM-BE9': ['SR-MGM-BE9_ref'], 'SR-MGN-BE107': ['SR-MGN-BE107_ref'],
    'SR-TM-BE15': ['SR-TML-BE11_ref','SR-TMD-BE4_ref'], 'MR-MGM-BE4': ['MR-MGM-BE4_ref'], 'MR-MGN-BE17': ['MR-MGN-BE17_ref'],
    'IsoL6-noopt': ['IsoL6_ref'], 'IP23': ['IP23_ref'], 'EA13': ['EA13_ref'], 'PA8': ['PA8_ref'],
    'πTC13': ['πIE3_ref', 'πPa10_ref'], 'HTBH38': ['HTBH38_ref'], 'NHTBH38': ['NHTBH38_ref'],
    'MR-TM-BE11': ['MR-TMD-BE3_ref', 'MR-TML-BE12_ref'], 'SMAE3': ['SMAE3_ref'],
    'NCCE34': ['CT7_ref', 'NCCE30_ref'], 'NGD21': ['NGD21_ref'], 'AE17': ['AE17_ref'], 'HC7': ['HC7_ref'],
    '3dEE8': ['3dEE8_ref'], '4dAEE5': ['4dAEE5_ref'],'pAEE5': ['pAEE5_ref'] ,'DC9': ['DC9_ref'],
    '4pIsoE4': ['4pIsoE4_ref'], '2pIsoE4': ['2pIsoE4_ref'],
    'INPUT':['INPUT_ref']}

weight ={'SR-MGM-BE9_ref': 0.84007544444138,
 'SR-MGN-BE107_ref': 0.93761699868819,
 'SR-TML-BE11_ref': 3.21975908756633,
 'SR-TMD-BE4_ref': 3.21975908756633,
 'MR-MGM-BE4_ref': 0.794188106818777,
 'MR-MGN-BE17_ref': 3.34206440048416,
 'MR-TML-BE12_ref': 3.40955630343526,
 'MR-TMD-BE3_ref': 1.09680397562565,
 'HTBH38_ref': 0.208536487179584,
 'NHTBH38_ref': 0.15567178804468,
 'NGD21_ref': 0.269857816544089,
 '3dEE8_ref': 1.72154629663685,
 '4dAEE5_ref': 0.82047217938509,
 'pAEE5_ref': 3.19879188702116,
 'IsoL6_ref': 1.1202180987861,
 '2pIsoE4_ref': 1.34523845405822,
 '4pIsoE4_ref': 1.25231726783512,
 'HC7_ref': 1.91482269957533,
 'IP23_ref': 1.77270480585249,
 'EA13_ref': 1.1353555118957,
 'PA8_ref': 0.925867114154515,
 'AE17_ref': 4.64260477211675,
 'DC9_ref': 4.87331824365315,
 'SMAE3_ref': 0.936054611968975,
 'NCCE30_ref': 0.06937893786996,
 'CT7_ref': 0.10607410747309,
 'πIE3_ref': 0.83368920833887,
 'πPa10_ref': 0.396789968023809,
 'A21x12_ref': 0.0571307354236068,
 'A24_ref': 0.063257144971844,
 'AlkAtom19_ref': 0.10796324887635,
 'AlkIsomer11_ref': 0.0621534242356776,
 'AlkIsod14_ref': 0.0994137376589614,
 'Bauza30_ref': 0.0845385608023336,
 'Butanediol65_ref': 0.00729174118843758,
 'BzDC215_ref': 0.220917369543102,
 'CT20_ref': 0.106205797933231,
 'DIE60_ref': 0.386744057684168,
 'DS14_ref': 0.102028394460809,
 'EIE22_ref': 0.404590317052526,
 'FmH2O10_ref': 0.55665049878394,
 'ACONF_ref': 0.0470949087032059,
 'CYCONF_ref': 0.107739084275295,
 'G21EA_ref': 1.90607330869041,
 'G21IP_ref': 2.82002986958659,
 'NBPRC_ref': 1.26233091215391,
 'WATER27_ref': 0.680800858197267,
 'H2O6Bind8_ref': 0.114043547268072,
 'HB15_ref': 0.169787379567986,
 'HW30_ref': 0.221467865969466,
 'HW6Cl_ref': 1.11476589792838,
 'HW6F_ref': 0.098932713726616,
 'NC15_ref': 0.0673773550921976,
 'Pentane14_ref': 0.025206045980193,
 'Shields38_ref': 0.337077667196769,
 'SW49Rel345_ref': 0.086729379287168,
 'SW49Bind345_ref': 0.132721863642345,
 'SW49Rel6_ref': 0.0614771927944955,
 'SW49Bind6_ref': 0.151315755027095,
 'TA13_ref': 0.205649367424055,
 'BHPERI26_ref': 0.134345364796769,
 'CR20_ref': 0.316476072999806,
 'CRBH20_ref': 0.591281837414385,
 'AlkBind12_ref': 0.188792518174541,
 'HB49_ref': 0.160655622103171,
 'Ionic43_ref': 0.454492574207733,
 'H2O20Bind4_ref': 0.445100727211908,
 'H2O20Rel4_ref': 0.148366909070653,
 'H2O20Bind10_ref': 0.313481213286397,
 'H2O20Rel10_ref': 0.145621900807468,
 'H2O16Rel5_ref': 0.0362257648813192,
 'BSR36_ref': 0.331057631121412,
 'HNBrBDE18_ref': 1.11917490604133,
 'PlatonicTAE6_ref': 0.513936470161187,
 'PlatonicIG6_ref': 4.06766640678643,
 'PlatonicID6_ref': 0.302793825908775,
 'PlatonicHD6_ref': 4.67473907905172,
 'PX13_ref': 1.75769463189025,
 'CE20_ref': 0.155003898861968,
 'WCPT27_ref': 0.283915539542914,
 'WCPT6_ref': 0.148775463816488,
 'HAT707MR_ref': 0.109243363632885,
 'HAT707nonMR_ref': 0.136554204541106,
 'TAE140MR_ref': 0.487640008041818,
 'TAE140nonMR_ref': 0.162546669347273,
 'BDE99MR_ref': 0.234609257950233,
 'BDE99nonMR_ref': 0.293261572437791,
 'ISOMERIZATION20_ref': 0.278645726873492,
 'SN13_ref': 0.106690688411982,
 'BH76RC_ref': 0.0813142431835875,
 'DBH24_ref': 0.0550079729038863,
 'INPUT_ref': 0.02}

_CUT = [3, 7, 42]
_FTOL = 1e-12
_SEGMENTS = (6, 5, 4, 3, 5, 4, 3, 4, 3, 3)

TrainDataSet = CFXXD_Train_Data_Set(
    database=database2,
    ref_root_path='./Database_updated/ref',
    fit_root_path='./Database_updated/fit',
    cut=_CUT,
    weight=weight,
)
fit_data, ratios, masks = TrainDataSet.fit_data, TrainDataSet.ratios, TrainDataSet.masks
loss_sort, weight = TrainDataSet.dictsort()
ref_names = TrainDataSet.ref_names


def _build_design_groups():
    groups = []
    for x, ratio, mask in zip(fit_data, ratios, masks):
        x = np.asarray(x, dtype=np.float64)
        ratio = np.asarray(ratio, dtype=np.float64)
        mask = np.asarray(mask, dtype=np.float64)
        count = x.shape[1]
        features = x[:, :, 1:60] - x[:, :, [0]]
        weighted = ratio[:, :count] * mask
        design = 627.509 * np.einsum('ij,ijk->ik', weighted, features) / ratio[:, -2, None]
        intercept = (
            627.509 * np.sum(
                weighted * (x[:, :, 0] + x[:, :, 60] + x[:, :, 61] / 627.509),
                axis=1,
            )
            - ratio[:, -1] * ratio[:, -3]
        ) / ratio[:, -2]
        if not (np.all(np.isfinite(design)) and np.all(np.isfinite(intercept))):
            raise ValueError('Non-finite values in optimizer design matrix')
        groups.append((design, intercept))
    return groups


_DESIGN_GROUPS = _build_design_groups()
_DESIGN_MATRIX = np.concatenate([design for design, _ in _DESIGN_GROUPS])
_INTERCEPT = np.concatenate([intercept for _, intercept in _DESIGN_GROUPS])
_LOSS_INDEXES = [np.asarray(index, dtype=np.intp) for index in loss_sort]
_LOSS_WEIGHTS = np.asarray(weight, dtype=np.float64)


def _residuals(theta):
    theta = np.asarray(theta, dtype=np.float64)
    if theta.shape != (59,) or not np.all(np.isfinite(theta)):
        raise ValueError('Expected 59 finite optimization parameters')
    return _DESIGN_MATRIX @ theta + _INTERCEPT


def _regularization(theta):
    value = 0.0
    gradient = np.zeros(59, dtype=np.float64)
    offset = 0
    for size in _SEGMENTS:
        difference = theta[offset:offset + size - 1] - theta[offset + 1:offset + size]
        value += 0.01 * float(np.dot(difference, difference))
        gradient[offset:offset + size - 1] += 0.02 * difference
        gradient[offset + 1:offset + size] -= 0.02 * difference
        offset += size
    for start, stop in ((40, 48), (49, 57)):
        difference = theta[start:stop] - theta[start + 1:stop + 1]
        value += 0.01 * float(np.dot(difference, difference))
        gradient[start:stop] += 0.02 * difference
        gradient[start + 1:stop + 1] -= 0.02 * difference
    return value, gradient


def loss_dataset(theta):
    residual = _residuals(theta)
    value, _ = _regularization(np.asarray(theta, dtype=np.float64))
    for indexes, inverse_weight in zip(_LOSS_INDEXES, _LOSS_WEIGHTS):
        value += float(np.sqrt(np.mean(residual[indexes] ** 2)) / inverse_weight)
    return float(value)


def loss_dataset_jac(theta):
    theta = np.asarray(theta, dtype=np.float64)
    residual = _residuals(theta)
    gradient = np.zeros(59, dtype=np.float64)
    for indexes, inverse_weight in zip(_LOSS_INDEXES, _LOSS_WEIGHTS):
        selected = residual[indexes]
        rmse = float(np.sqrt(np.mean(selected ** 2)))
        if rmse == 0.0:
            continue
        design = _DESIGN_MATRIX[indexes]
        gradient += design.T @ selected / (len(indexes) * rmse * inverse_weight)
    _, regularization_gradient = _regularization(theta)
    gradient += regularization_gradient
    if not np.all(np.isfinite(gradient)):
        raise ValueError('Non-finite optimizer gradient')
    return gradient


def residual_dataset_all(theta):
    theta = np.asarray(theta, dtype=np.float64)
    residual = _residuals(theta)
    # Keep the historical result schema: a is all Cx smoothness terms,
    # while b and c are the Cy and Cz smoothness terms.
    c_x_regularization = 0.0
    offset = 0
    for size in _SEGMENTS:
        difference = theta[offset:offset + size - 1] - theta[offset + 1:offset + size]
        c_x_regularization += float(np.dot(difference, difference))
        offset += size
    b_difference = theta[40:48] - theta[41:49]
    c_difference = theta[49:57] - theta[50:58]
    result = {
        'a': {'RMSE': c_x_regularization},
        'b': {'RMSE': float(np.dot(b_difference, b_difference))},
        'c': {'RMSE': float(np.dot(c_difference, c_difference))},
    }
    for indexes, name in zip(_LOSS_INDEXES, ref_names):
        selected = residual[indexes]
        result[name] = {
            'RMSE': float(np.sqrt(np.mean(selected ** 2))),
            'MUE': float(np.mean(np.abs(selected))),
            'res': selected.tolist(),
        }
    return result


class ScipySLSQPSolver:
    method = 'SLSQP'

    def __init__(self, fun, jac, maxiter=10000, ftol=_FTOL):
        self.fun = fun
        self.jac = jac
        self.maxiter = int(maxiter)
        self.ftol = float(ftol)
        self.options = {'ftol': self.ftol, 'maxiter': self.maxiter}

    def run(self, theta0):
        result = minimize(
            self.fun,
            np.asarray(theta0, dtype=np.float64),
            jac=self.jac,
            method=self.method,
            options=self.options,
        )
        result.params = np.asarray(result.x, dtype=np.float64)
        result.state = SimpleNamespace(
            success=bool(result.success),
            status=int(result.status),
            iter_num=int(getattr(result, 'nit', 0)),
            num_fun_eval=int(getattr(result, 'nfev', 0)),
            num_jac_eval=int(getattr(result, 'njev', 0)),
        )
        return result


_theta0 = np.asarray(np.loadtxt('params.txt'), dtype=np.float64)
if _theta0.shape == (58,):
    _theta0 = np.concatenate([_theta0, np.asarray([0.462806], dtype=np.float64)])
if _theta0.shape != (59,) or not np.all(np.isfinite(_theta0)):
    raise ValueError('Expected 59 finite initial parameters')
theta0 = _theta0
solver = ScipySLSQPSolver(loss_dataset, loss_dataset_jac, maxiter=10000, ftol=_FTOL)
res = solver.run(theta0)
if not res.state.success:
    raise RuntimeError(f'SLSQP failed: {res.message}')
np.savetxt('NEW-params.txt', res.params, fmt='%.17g')
from saver import save_dict_to_json
save_dict_to_json(residual_dataset_all(res.params))
