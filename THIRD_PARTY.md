# Third-party components

DFThub is distributed under the repository MIT license. The bundled xclib
descriptor code is from Yuhao Chen's CF25D project. CF22D fitting/reference
data retain their original dataset identifiers and scientific provenance.

PySCF DFT is a separate wheel, under Apache-2.0; its LICENSE and NOTICE remain
inside that wheel. It is built from chen-yu-hao/pyscf, DFT commit 72e5b26c.
The repaired wheel includes native dependencies; LibXC 7.1.2 (MPL-2.0),
libcint 6.2.0 (Apache-2.0), XCFun (MPL-2.0), and BLAS/OpenMP runtime licenses
apply to their respective components. Their sources/build references are
recorded in the engine manifest and release source assets.

Swagger UI 5.18.3 is Apache-2.0 and is bundled under static/vendor/swagger,
including its LICENSE. Frontend dependencies retain their package licenses.
