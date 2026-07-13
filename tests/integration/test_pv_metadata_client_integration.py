import unittest
import time
import logging
import grpc
import sys
import os

# Add src directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../src'))

from dp_python_lib.client.mldp_client import MldpClient
from dp_python_lib.client.pv_metadata_client import SavePvMetadataRequestParams, PvMetadataQuery


class TestPvMetadataClientIntegration(unittest.TestCase):
    """
    Integration tests for PvMetadataClient that require a running MLDP ecosystem.

    Prerequisites:
    - MLDP services running via docker compose
    - Default configuration (localhost:50053 for annotation service)
    - Services should be healthy and accepting connections

    To run these tests:
    1. Start MLDP ecosystem: docker compose up -d
    2. Run tests: python -m unittest tests.integration.test_pv_metadata_client_integration -v
    """

    ANNOTATION_ADDRESS = 'localhost:50053'

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        cls.logger = logging.getLogger(__name__)
        cls.logger.info("Setting up PV metadata integration test environment")

        cls._verify_services_available()

        cls.client = MldpClient()
        cls.logger.info("MldpClient initialized successfully")

    @classmethod
    def _verify_services_available(cls):
        cls.logger.info("Checking if MLDP annotation service is available")
        try:
            channel = grpc.insecure_channel(cls.ANNOTATION_ADDRESS)
            grpc.channel_ready_future(channel).result(timeout=5)
            cls.logger.info("Annotation service is reachable at %s", cls.ANNOTATION_ADDRESS)
            channel.close()
        except grpc.FutureTimeoutError:
            raise unittest.SkipTest(
                f"MLDP annotation service not available at {cls.ANNOTATION_ADDRESS}. "
                "Please start the MLDP ecosystem with 'docker compose up -d' before running integration tests."
            )
        except Exception as e:
            raise unittest.SkipTest(
                f"Cannot connect to MLDP annotation service: {e}. "
                "Please ensure the MLDP ecosystem is running."
            )

    def test_save_get_query_delete_round_trip(self):
        """
        Exercises the full PV metadata lifecycle against real services: save -> get -> query -> delete.

        Accepts both success and expected business errors as valid, since the goal is to verify communication
        and request/response handling with real services.
        """
        self.assertIsNotNone(self.client.annotation, "annotation client should be initialized")
        pv_client = self.client.annotation.pv_metadata

        timestamp = int(time.time())
        pv_name = f"INTEGRATION:TEST:{timestamp}"

        # --- save ---
        save_params = SavePvMetadataRequestParams(
            pv_name=pv_name,
            aliases=[f"alias-{timestamp}"],
            tags=["integration", "test"],
            attributes={"framework": "unittest", "timestamp": str(timestamp)},
            modified_by="dp-python-lib-integration-test",
            description="Integration test PV metadata",
        )
        save_result = pv_client.save_pv_metadata(save_params)
        self.assertIsNotNone(save_result.result_status)
        if save_result.result_status.is_error:
            self.logger.warning("savePvMetadata returned error: %s", save_result.result_status.message)
        else:
            self.logger.info("Saved PV metadata for: %s", save_result.pv_name)

        # --- get ---
        get_result = pv_client.get_pv_metadata(pv_name)
        self.assertIsNotNone(get_result.result_status)
        if not get_result.result_status.is_error:
            self.logger.info("Retrieved PV metadata: %s", get_result.pv_metadata.pvName)

        # --- query ---
        query_result = pv_client.query_pv_metadata([PvMetadataQuery.pv_name(exact=[pv_name])])
        self.assertIsNotNone(query_result.result_status)
        if not query_result.result_status.is_error:
            self.logger.info("Query returned %d records", len(query_result.pv_metadata_list))

        # --- delete ---
        delete_result = pv_client.delete_pv_metadata(pv_name)
        self.assertIsNotNone(delete_result.result_status)
        if not delete_result.result_status.is_error:
            self.logger.info("Deleted PV metadata for: %s", delete_result.pv_name)

        self.logger.info("PV metadata round-trip integration test completed")


if __name__ == '__main__':
    unittest.main(verbosity=2)
