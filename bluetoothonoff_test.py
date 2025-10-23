import unittest
import time
import bluetoothonoff as mod


# f1 = "/var/log/000_la_gvm.txt "
# f2 = "/var/log/la_gvm.txt" 
# f3 = "/var/log/fastrpc_debug.farf"




# class TestQnxFaultDetectLive(unittest.TestCase):
#     def setUp(self):

#         # Use the module's constants: QNX_COM_PORT should be "COM13"
#         self.qnx = mod.SerialWorker(name="QNX", port_name=mod.QNX_COM_PORT, baudrate=mod.DEFAULT_BAUD)
#         self.qnx.start()

#         # Give the reader thread and serial port a moment to initialize
#         time.sleep(0.5)

#     def tearDown(self):

#         self.qnx.stop()

#     def test_live_fault_detection_smoke(self):

#         # 1) Confirm the serial port opened successfully
#         self.assertIsNotNone(self.qnx.ser, "Serial object was not created.")
#         self.assertTrue(self.qnx.ser.is_open, "COM13 did not open. Check device and drivers.")

#         paths = [f1,f2,f3]
#         probe_results = []
#         for p in paths:
#             ok = mod.qnx_path_exists(self.qnx, p, timeout=5.0)
#             self.assertIsInstance(ok, bool, f"Probe for {p} did not return a boolean.")
#             probe_results.append(ok)

#         result = mod.qnx_fault_detect(self.qnx, timeout=5.0)
#         self.assertIsInstance(result, bool, "qnx_fault_detect did not return a boolean.")

#         # 4) Optional consistency check:
#         #    qnx_fault_detect returns True if ANY of the indicators exist.
#         #    Compare to our per-path probes (within the same short window).
#         #    If the device state changes rapidly, you can comment this out.
#         expected_any = any(probe_results)  
#         self.assertEqual(result, expected_any, "qnx_fault_detect result differs from direct probes.")

#         # NOTE: When faults exist, qnx_fault_detect may also pull files or move the core.
#         #       That behavior is validated in the mocked unit tests. Here, we only verify live connectivity.



class TestQNX(unittest.TestCase):

    def test_qnx_sendcommand(self):
        test=mod.TestController()
        test.start_workers()
        text='echo "aaaaaa" > /var/log/display_smmu_fault_info.txt'

        test.workers["QNX"].send_command(text)
        text='echo "bbbbbb" > /var/log/postmortem_smmu.txt'
        test.workers["QNX"].send_command(text)
        text='echo "cccc" > /var/log/openwfd_server-QM.core'
        test.workers["QNX"].send_command(text)
        test.stop_workers()
        mod.main()

# text_create=mod.SerialWorker.get_serial()
# text_create.send_comman


# class TestQnxFaultDetectPULLANDMOVE(unittest.TestCase):
#     def setUp(self):
#         # Start a real QNX serial worker on COM13
#         self.qnx = mod.SerialWorker(name="QNX", port_name=mod.QNX_COM_PORT, baudrate=mod.DEFAULT_BAUD)
#         self.qnx.start()
#         time.sleep(0.5)  # give the thread time

#         self.custom_texts = [
#             "f1.txt","f2.txt","f3.txt"
#         ]
#         self.custom_core = "/var/log/openwfd_server-QM.core"  # keep or change if you have another core path

#     def tearDown(self):
#         self.qnx.stop()

#     def test_live_custom_fault_detection(self):
#         probe = [mod.qnx_path_exists(self.qnx, p, timeout=5.0) for p in self.custom_texts]
#         core_probe = mod.qnx_path_exists(self.qnx, self.custom_core, timeout=5.0)

#         result = mod.qnx_fault_detect(
#             self.qnx,
#             timeout=5.0,
#             fault_text_files=self.custom_texts,
#             core_file=self.custom_core,
#         )

#         expected_any = any(probe) or core_probe
#         self.assertEqual(result, expected_any, "Custom fault detection inconsistent with direct probes.")

if __name__ == "__main__":
    unittest.main()
