. "$IDF_PATH/export.sh" >/dev/null 2>&1
bash /m1/run_app.sh i2c_attach esp32 I2C_ATTACH_DONE >/dev/null 2>&1
python3 /m1/q2c_qomset.py
