# DFThub upload template

This archive is a format reference. Replace the example names, geometries and reference values with your own data.

## Training upload

Upload these files through **New job**:

- `YourDatabaseName.tgz`: an archive containing `.xyz` files.
- `YourDatabaseName.ref`: whitespace-separated reaction expressions and reference values.

The names in `.ref` must match the `.xyz` filenames without `.xyz`.

## Optional test upload

Upload a matching optional pair when needed:

- `test_YourTestSet.tgz`
- `test_YourTestSet.ref`

The test set is evaluated after fitting and during Input SCF. It is excluded from optimization.
