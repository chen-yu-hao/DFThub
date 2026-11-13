"""Read the native LibXC CF22D coefficients in DFThub descriptor order."""
import ctypes
import hashlib


def native_cf22d_parameters():
    import numpy as np
    import pyscf
    from pyscf.dft import libxc

    library = libxc._itrf
    library.xc_func_info_get_ext_params_name.argtypes = [ctypes.c_void_p, ctypes.c_int]
    library.xc_func_info_get_ext_params_name.restype = ctypes.c_char_p
    library.xc_func_info_get_ext_params_default_value.argtypes = [ctypes.c_void_p, ctypes.c_int]
    library.xc_func_info_get_ext_params_default_value.restype = ctypes.c_double
    defaults = {}
    for functional_id, pointer in libxc._get_xc('CF22D,CF22D').obj_by_id().items():
        info = library.xc_func_get_info(pointer)
        defaults[int(functional_id)] = {
            library.xc_func_info_get_ext_params_name(info, index).decode():
                library.xc_func_info_get_ext_params_default_value(info, index)
            for index in range(library.xc_func_info_get_n_ext_params(info))
        }
    if set(defaults) != {340, 341}:
        raise ValueError('Unexpected LibXC CF22D components')
    exchange_names = [f'_CC{i}{j}{k}' for i in range(4) for j in range(4 - i) for k in range(6 - i - j)]
    # The descriptor basis has nine terms in each correlation expansion.
    if any(defaults[341][f'_{group}{index}'] != 0 for group in ('a', 'b') for index in range(9, 12)):
        raise ValueError('Native CF22D needs correlation terms absent from the descriptor basis')
    coefficients = ([defaults[340][name] for name in exchange_names]
                    + [defaults[341][f'_a{i}'] for i in range(9)]
                    + [defaults[341][f'_b{i}'] for i in range(9)]
                    + [defaults[340]['_ax']])
    if len(coefficients) != 59 or not np.isfinite(coefficients).all():
        raise ValueError('Invalid native CF22D coefficient vector')
    if abs(coefficients[-1] - libxc.hybrid_coeff('CF22D,CF22D')) > 1e-14:
        raise ValueError('CF22D hybrid coefficient disagrees with LibXC defaults')
    return {
        'source': 'libxc-native-cf22d', 'functional': 'CF22D',
        'pyscf_version': pyscf.__version__, 'libxc_version': libxc.libxc_version(),
        'parameter_sha256': hashlib.sha256(np.asarray(coefficients, dtype='<f8').tobytes()).hexdigest(),
        'coefficient_names': exchange_names + [f'_a{i}' for i in range(9)] + [f'_b{i}' for i in range(9)] + ['HF'],
        'coefficients': coefficients,
        'evaluation': 'Native CF22D parameters evaluated on stored descriptors with existing dispersion contributions; no new SCF.',
    }
