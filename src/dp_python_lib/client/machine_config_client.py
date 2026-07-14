from datetime import datetime, timezone
from typing import Optional, Dict, List, Iterator, Union
from dp_python_lib.client.service_api_client_base import ServiceApiClientBase
from dp_python_lib.client.result import ApiResultBase
from dp_python_lib.grpc import annotation_pb2_grpc
from dp_python_lib.grpc import annotation_pb2
from dp_python_lib.grpc import common_pb2
import grpc
import logging


# Accepted input types for API parameters that map to a common.Timestamp:
# a timezone-aware datetime, epoch seconds (int or float), or an already-built Timestamp.
TimestampInput = Union[datetime, int, float, common_pb2.Timestamp]


def to_timestamp(value: TimestampInput) -> common_pb2.Timestamp:
    """
    Converts a user-supplied time value into a common.Timestamp{epochSeconds, nanoseconds}.

    Accepts:
      - a timezone-aware datetime (naive datetimes are rejected to avoid silent local-timezone bugs),
      - epoch seconds as an int or float (float fractional part becomes nanoseconds),
      - an already-built common.Timestamp (returned as-is).

    :param value: The time value to convert.
    :return: An equivalent common.Timestamp.
    :raises ValueError: if a datetime is naive (has no tzinfo).
    :raises TypeError: if value is not one of the supported types.
    """
    if isinstance(value, common_pb2.Timestamp):
        return value

    if isinstance(value, datetime):
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError(
                "to_timestamp() requires a timezone-aware datetime; naive datetimes are rejected "
                "to avoid silent local-timezone bugs. Use datetime.now(timezone.utc) or attach tzinfo."
            )
        epoch = value.timestamp()
        return to_timestamp(epoch)

    if isinstance(value, bool):
        # bool is a subclass of int; reject it explicitly as it is virtually always a mistake.
        raise TypeError("to_timestamp() does not accept bool")

    if isinstance(value, (int, float)):
        epoch_seconds = int(value)
        nanoseconds = int(round((float(value) - epoch_seconds) * 1_000_000_000))
        # Guard against float rounding pushing nanoseconds to a full second.
        if nanoseconds >= 1_000_000_000:
            epoch_seconds += 1
            nanoseconds -= 1_000_000_000
        timestamp = common_pb2.Timestamp()
        timestamp.epochSeconds = epoch_seconds
        timestamp.nanoseconds = nanoseconds
        return timestamp

    raise TypeError(
        f"to_timestamp() expects datetime, int/float epoch seconds, or common.Timestamp, got {type(value).__name__}"
    )


class ConfigurationQuery:
    """
    Factory of lightweight helpers for building QueryConfigurationsRequest.QueryConfigurationsCriterion objects for use
    with MachineConfigClient.query_configurations() and iter_configurations().  Each helper returns a single criterion;
    callers pass a list of criteria to the query methods.

    Example:
        from dp_python_lib.client import ConfigurationQuery as C
        criteria = [C.name(prefix=["beamline-"]), C.tags(["production"])]
        result = client.annotation.machine_config.query_configurations(criteria=criteria)
    """

    _Criterion = annotation_pb2.QueryConfigurationsRequest.QueryConfigurationsCriterion

    @staticmethod
    def name(exact: Optional[List[str]] = None, prefix: Optional[List[str]] = None,
             contains: Optional[List[str]] = None) -> "annotation_pb2.QueryConfigurationsRequest.QueryConfigurationsCriterion":
        """
        Builds a criterion matching configuration names by exact value, prefix, and/or substring.
        :param exact: Configuration names to match exactly.
        :param prefix: Configuration name prefixes to match.
        :param contains: Substrings the configuration name must contain.
        :return: A QueryConfigurationsCriterion with a nameCriterion.
        :raises ValueError: if none of exact/prefix/contains is provided and non-empty.
        """
        if not (exact or prefix or contains):
            raise ValueError("name() requires at least one non-empty of exact/prefix/contains")
        criterion = ConfigurationQuery._Criterion()
        name_criterion = criterion.nameCriterion
        if exact:
            name_criterion.exact[:] = exact
        if prefix:
            name_criterion.prefix[:] = prefix
        if contains:
            name_criterion.contains[:] = contains
        return criterion

    @staticmethod
    def category(values: List[str]) -> "annotation_pb2.QueryConfigurationsRequest.QueryConfigurationsCriterion":
        """
        Builds a criterion matching configurations having any of the specified categories.
        :param values: Category values to match.
        :return: A QueryConfigurationsCriterion with a categoryCriterion.
        :raises ValueError: if values is empty.
        """
        if not values:
            raise ValueError("category() requires a non-empty values list")
        criterion = ConfigurationQuery._Criterion()
        criterion.categoryCriterion.values[:] = values
        return criterion

    @staticmethod
    def tags(values: List[str]) -> "annotation_pb2.QueryConfigurationsRequest.QueryConfigurationsCriterion":
        """
        Builds a criterion matching configurations having any of the specified tags.
        :param values: Tag values to match.
        :return: A QueryConfigurationsCriterion with a tagsCriterion.
        :raises ValueError: if values is empty.
        """
        if not values:
            raise ValueError("tags() requires a non-empty values list")
        criterion = ConfigurationQuery._Criterion()
        criterion.tagsCriterion.values[:] = values
        return criterion

    @staticmethod
    def attributes(key: str, values: List[str]) -> "annotation_pb2.QueryConfigurationsRequest.QueryConfigurationsCriterion":
        """
        Builds a criterion matching configurations whose attribute with the given key has any of the specified values.
        :param key: Attribute key to match.
        :param values: Attribute values to match for that key.
        :return: A QueryConfigurationsCriterion with an attributesCriterion.
        :raises ValueError: if key is empty or values is empty.
        """
        if not key:
            raise ValueError("attributes() requires a non-empty key")
        if not values:
            raise ValueError("attributes() requires a non-empty values list")
        criterion = ConfigurationQuery._Criterion()
        criterion.attributesCriterion.key = key
        criterion.attributesCriterion.values[:] = values
        return criterion

    @staticmethod
    def parent(values: List[str]) -> "annotation_pb2.QueryConfigurationsRequest.QueryConfigurationsCriterion":
        """
        Builds a criterion matching configurations whose parent configuration name is any of the specified values.
        :param values: Parent configuration names to match.
        :return: A QueryConfigurationsCriterion with a parentCriterion.
        :raises ValueError: if values is empty.
        """
        if not values:
            raise ValueError("parent() requires a non-empty values list")
        criterion = ConfigurationQuery._Criterion()
        criterion.parentCriterion.values[:] = values
        return criterion


class SaveConfigurationRequestParams:
    """
    Encapsulates client parameters for a call to the saveConfiguration() API method.
    """

    def __init__(self, configuration_name: str, category: Optional[str] = None, description: Optional[str] = None,
                 parent_configuration_name: Optional[str] = None, tags: Optional[List[str]] = None,
                 attributes: Optional[Dict[str, str]] = None, modified_by: Optional[str] = None) -> None:
        """
        :param configuration_name: Name of the machine configuration being saved.
        :param category: Category grouping for the configuration.
        :param description: Human-readable description of the configuration.
        :param parent_configuration_name: Name of the parent configuration, for hierarchical configurations.
        :param tags: List of tags (keywords) describing the configuration.
        :param attributes: Map of key/value attributes describing the configuration.
        :param modified_by: Identifier of the user or process making the change.
        """
        self.configuration_name = configuration_name
        self.category = category
        self.description = description
        self.parent_configuration_name = parent_configuration_name
        self.tags = tags
        self.attributes = attributes
        self.modified_by = modified_by


class SaveConfigurationApiResult(ApiResultBase):
    """
    Wraps the response from saveConfiguration(), with a status object including an error flag and message.
    """

    def __init__(self, is_error: bool, message: str,
                 response: Optional[annotation_pb2.SaveConfigurationResponse] = None) -> None:
        """
        :param is_error: Boolean flag indicating if an error occurred in the API call.
        :param message: Error message describing the error condition.
        :param response: The SaveConfigurationResponse returned by the API call, or None.
        """
        super().__init__(is_error, message)
        self.response = response

    @property
    def configuration_name(self) -> Optional[str]:
        """Name of the configuration that was saved, or None on error."""
        if self.response is not None and self.response.HasField('saveConfigurationResult'):
            return self.response.saveConfigurationResult.configurationName
        return None


class GetConfigurationApiResult(ApiResultBase):
    """
    Wraps the response from getConfiguration(), with a status object including an error flag and message.
    """

    def __init__(self, is_error: bool, message: str,
                 response: Optional[annotation_pb2.GetConfigurationResponse] = None) -> None:
        """
        :param is_error: Boolean flag indicating if an error occurred in the API call.
        :param message: Error message describing the error condition.
        :param response: The GetConfigurationResponse returned by the API call, or None.
        """
        super().__init__(is_error, message)
        self.response = response

    @property
    def configuration(self) -> Optional[common_pb2.Configuration]:
        """The Configuration for the requested name, or None on error."""
        if self.response is not None and self.response.HasField('getConfigurationResult'):
            return self.response.getConfigurationResult.configuration
        return None


class QueryConfigurationsApiResult(ApiResultBase):
    """
    Wraps a single page of the response from queryConfigurations(), with a status object including an error flag and
    message.  Use MachineConfigClient.iter_configurations() to transparently page through all results.
    """

    def __init__(self, is_error: bool, message: str,
                 response: Optional[annotation_pb2.QueryConfigurationsResponse] = None) -> None:
        """
        :param is_error: Boolean flag indicating if an error occurred in the API call.
        :param message: Error message describing the error condition.
        :param response: The QueryConfigurationsResponse returned by the API call, or None.
        """
        super().__init__(is_error, message)
        self.response = response

    @property
    def configurations(self) -> List[common_pb2.Configuration]:
        """The Configuration records in this page, or an empty list on error."""
        if self.response is not None and self.response.HasField('queryConfigurationsResult'):
            return list(self.response.queryConfigurationsResult.configurations)
        return []

    @property
    def next_page_token(self) -> str:
        """Token for retrieving the next page, or empty string if there are no more pages."""
        if self.response is not None and self.response.HasField('queryConfigurationsResult'):
            return self.response.queryConfigurationsResult.nextPageToken
        return ""


class DeleteConfigurationApiResult(ApiResultBase):
    """
    Wraps the response from deleteConfiguration(), with a status object including an error flag and message.
    """

    def __init__(self, is_error: bool, message: str,
                 response: Optional[annotation_pb2.DeleteConfigurationResponse] = None) -> None:
        """
        :param is_error: Boolean flag indicating if an error occurred in the API call.
        :param message: Error message describing the error condition.
        :param response: The DeleteConfigurationResponse returned by the API call, or None.
        """
        super().__init__(is_error, message)
        self.response = response

    @property
    def configuration_name(self) -> Optional[str]:
        """Name of the configuration that was deleted, or None on error."""
        if self.response is not None and self.response.HasField('deleteConfigurationResult'):
            return self.response.deleteConfigurationResult.configurationName
        return None


class MachineConfigClient(ServiceApiClientBase):
    """
    User-facing client for the machine configuration methods of the MLDP Annotation Service.  Covers both machine
    configurations (saveConfiguration/getConfiguration/queryConfigurations/deleteConfiguration) and, in a later phase,
    their temporal activations.  Provides low-level wrappers plus conveniences such as dict/list inputs and an
    iter_configurations() paging iterator.
    """

    def __init__(self, channel: grpc.Channel) -> None:
        """
        :param channel: gRPC communication channel for the Annotation Service.
        """
        super().__init__(channel, annotation_pb2_grpc.DpAnnotationServiceStub)
        self.logger = logging.getLogger(__name__)
        self.logger.debug("MachineConfigClient initialized with channel: %s", channel)

    # ------------------------------------------------------------------
    # saveConfiguration
    # ------------------------------------------------------------------

    def _build_save_configuration_request(
            self, request_params: SaveConfigurationRequestParams) -> annotation_pb2.SaveConfigurationRequest:
        """
        Builds a SaveConfigurationRequest from the supplied SaveConfigurationRequestParams.
        :param request_params: User parameters for the call to saveConfiguration().
        :return: A SaveConfigurationRequest for the specified params.
        """
        self.logger.debug("Building SaveConfigurationRequest for configuration: %s",
                          request_params.configuration_name)

        request = annotation_pb2.SaveConfigurationRequest()
        request.configurationName = request_params.configuration_name

        if request_params.category:
            request.category = request_params.category

        if request_params.description:
            request.description = request_params.description

        if request_params.parent_configuration_name:
            request.parentConfigurationName = request_params.parent_configuration_name

        if request_params.tags:
            request.tags[:] = request_params.tags

        if request_params.attributes:
            for name, value in request_params.attributes.items():
                attribute = common_pb2.Attribute()
                attribute.name = name
                attribute.value = value
                request.attributes.append(attribute)

        if request_params.modified_by:
            request.modifiedBy = request_params.modified_by

        self.logger.debug("SaveConfigurationRequest built successfully")
        return request

    def _send_save_configuration(
            self, request: annotation_pb2.SaveConfigurationRequest) -> SaveConfigurationApiResult:
        """
        Invokes the saveConfiguration() API method with the supplied request.
        :param request: SaveConfigurationRequest with parameters for the call.
        :return: A SaveConfigurationApiResult with the method response and status information.
        """
        self.logger.info("Calling saveConfiguration API for configuration: %s", request.configurationName)

        try:
            self.logger.debug("Invoking stub.saveConfiguration with request")
            response = self._stub.saveConfiguration(request)
            self.logger.debug("Received response from saveConfiguration API")

            if response.HasField('exceptionalResult'):
                error_msg = response.exceptionalResult.message
                self.logger.warning("SaveConfiguration API returned business error: %s", error_msg)
                return SaveConfigurationApiResult(is_error=True, message=error_msg)

            elif response.HasField('saveConfigurationResult'):
                self.logger.info("Successfully saved configuration: %s", request.configurationName)
                return SaveConfigurationApiResult(is_error=False, message="", response=response)

            else:
                error_msg = "Unexpected response format: neither exceptionalResult nor saveConfigurationResult found"
                self.logger.error(error_msg)
                return SaveConfigurationApiResult(is_error=True, message=error_msg)

        except grpc.RpcError as e:
            error_msg = f"gRPC error: {e.details()}"
            self.logger.error("gRPC error during saveConfiguration: %s", e.details())
            return SaveConfigurationApiResult(is_error=True, message=error_msg)
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            self.logger.error("Unexpected error during saveConfiguration: %s", str(e), exc_info=True)
            return SaveConfigurationApiResult(is_error=True, message=error_msg)

    def save_configuration(self, request_params: SaveConfigurationRequestParams) -> SaveConfigurationApiResult:
        """
        User-facing method for invoking the saveConfiguration() API method.
        :param request_params: Contains user parameters for the call to saveConfiguration().
        :return: A SaveConfigurationApiResult with the method response and status information.
        """
        self.logger.info("Starting saveConfiguration operation for configuration: %s",
                        request_params.configuration_name)

        request = self._build_save_configuration_request(request_params)
        result = self._send_save_configuration(request)

        if result.result_status.is_error:
            self.logger.error("SaveConfiguration operation failed: %s", result.result_status.message)
        else:
            self.logger.info("SaveConfiguration operation completed successfully for: %s",
                            request_params.configuration_name)

        return result

    # ------------------------------------------------------------------
    # getConfiguration
    # ------------------------------------------------------------------

    def _build_get_configuration_request(self, configuration_name: str) -> annotation_pb2.GetConfigurationRequest:
        """
        Builds a GetConfigurationRequest for the supplied configuration name.
        :param configuration_name: Configuration name to look up.
        :return: A GetConfigurationRequest for the specified name.
        """
        self.logger.debug("Building GetConfigurationRequest for: %s", configuration_name)
        request = annotation_pb2.GetConfigurationRequest()
        request.configurationName = configuration_name
        return request

    def _send_get_configuration(
            self, request: annotation_pb2.GetConfigurationRequest) -> GetConfigurationApiResult:
        """
        Invokes the getConfiguration() API method with the supplied request.
        :param request: GetConfigurationRequest with parameters for the call.
        :return: A GetConfigurationApiResult with the method response and status information.
        """
        self.logger.info("Calling getConfiguration API for: %s", request.configurationName)

        try:
            self.logger.debug("Invoking stub.getConfiguration with request")
            response = self._stub.getConfiguration(request)
            self.logger.debug("Received response from getConfiguration API")

            if response.HasField('exceptionalResult'):
                error_msg = response.exceptionalResult.message
                self.logger.warning("GetConfiguration API returned business error: %s", error_msg)
                return GetConfigurationApiResult(is_error=True, message=error_msg)

            elif response.HasField('getConfigurationResult'):
                self.logger.info("Successfully retrieved configuration: %s", request.configurationName)
                return GetConfigurationApiResult(is_error=False, message="", response=response)

            else:
                error_msg = "Unexpected response format: neither exceptionalResult nor getConfigurationResult found"
                self.logger.error(error_msg)
                return GetConfigurationApiResult(is_error=True, message=error_msg)

        except grpc.RpcError as e:
            error_msg = f"gRPC error: {e.details()}"
            self.logger.error("gRPC error during getConfiguration: %s", e.details())
            return GetConfigurationApiResult(is_error=True, message=error_msg)
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            self.logger.error("Unexpected error during getConfiguration: %s", str(e), exc_info=True)
            return GetConfigurationApiResult(is_error=True, message=error_msg)

    def get_configuration(self, configuration_name: str) -> GetConfigurationApiResult:
        """
        User-facing method for invoking the getConfiguration() API method.
        :param configuration_name: Configuration name to look up.
        :return: A GetConfigurationApiResult with the method response and status information.
        """
        self.logger.info("Starting getConfiguration operation for: %s", configuration_name)

        request = self._build_get_configuration_request(configuration_name)
        result = self._send_get_configuration(request)

        if result.result_status.is_error:
            self.logger.error("GetConfiguration operation failed: %s", result.result_status.message)
        else:
            self.logger.info("GetConfiguration operation completed successfully for: %s", configuration_name)

        return result

    # ------------------------------------------------------------------
    # queryConfigurations
    # ------------------------------------------------------------------

    def _build_query_configurations_request(
            self, criteria: List[annotation_pb2.QueryConfigurationsRequest.QueryConfigurationsCriterion],
            limit: Optional[int] = None,
            page_token: Optional[str] = None) -> annotation_pb2.QueryConfigurationsRequest:
        """
        Builds a QueryConfigurationsRequest from the supplied criteria and paging parameters.
        :param criteria: List of QueryConfigurationsCriterion objects (see ConfigurationQuery helpers).
        :param limit: Maximum number of records to return per page (optional).
        :param page_token: Token for retrieving a subsequent page (optional).
        :return: A QueryConfigurationsRequest for the specified params.
        """
        self.logger.debug("Building QueryConfigurationsRequest with %d criteria", len(criteria))
        request = annotation_pb2.QueryConfigurationsRequest()
        request.criteria.extend(criteria)
        if limit is not None:
            request.limit = limit
        if page_token:
            request.pageToken = page_token
        return request

    def _send_query_configurations(
            self, request: annotation_pb2.QueryConfigurationsRequest) -> QueryConfigurationsApiResult:
        """
        Invokes the queryConfigurations() API method with the supplied request.
        :param request: QueryConfigurationsRequest with parameters for the call.
        :return: A QueryConfigurationsApiResult with the method response and status information.
        """
        self.logger.info("Calling queryConfigurations API with %d criteria", len(request.criteria))

        try:
            self.logger.debug("Invoking stub.queryConfigurations with request")
            response = self._stub.queryConfigurations(request)
            self.logger.debug("Received response from queryConfigurations API")

            if response.HasField('exceptionalResult'):
                error_msg = response.exceptionalResult.message
                self.logger.warning("QueryConfigurations API returned business error: %s", error_msg)
                return QueryConfigurationsApiResult(is_error=True, message=error_msg)

            elif response.HasField('queryConfigurationsResult'):
                self.logger.info("QueryConfigurations returned %d records",
                                 len(response.queryConfigurationsResult.configurations))
                return QueryConfigurationsApiResult(is_error=False, message="", response=response)

            else:
                error_msg = ("Unexpected response format: neither exceptionalResult nor "
                             "queryConfigurationsResult found")
                self.logger.error(error_msg)
                return QueryConfigurationsApiResult(is_error=True, message=error_msg)

        except grpc.RpcError as e:
            error_msg = f"gRPC error: {e.details()}"
            self.logger.error("gRPC error during queryConfigurations: %s", e.details())
            return QueryConfigurationsApiResult(is_error=True, message=error_msg)
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            self.logger.error("Unexpected error during queryConfigurations: %s", str(e), exc_info=True)
            return QueryConfigurationsApiResult(is_error=True, message=error_msg)

    def query_configurations(
            self, criteria: List[annotation_pb2.QueryConfigurationsRequest.QueryConfigurationsCriterion],
            limit: Optional[int] = None, page_token: Optional[str] = None) -> QueryConfigurationsApiResult:
        """
        User-facing method for invoking the queryConfigurations() API method.  Returns a single page of results; use
        iter_configurations() to page through all results transparently.
        :param criteria: List of QueryConfigurationsCriterion objects (see ConfigurationQuery helpers).
        :param limit: Maximum number of records to return per page (optional).
        :param page_token: Token for retrieving a subsequent page (optional).
        :return: A QueryConfigurationsApiResult with a single page of results and status information.
        """
        self.logger.info("Starting queryConfigurations operation with %d criteria", len(criteria))

        request = self._build_query_configurations_request(criteria, limit=limit, page_token=page_token)
        result = self._send_query_configurations(request)

        if result.result_status.is_error:
            self.logger.error("QueryConfigurations operation failed: %s", result.result_status.message)
        else:
            self.logger.info("QueryConfigurations operation completed successfully")

        return result

    def iter_configurations(
            self, criteria: List[annotation_pb2.QueryConfigurationsRequest.QueryConfigurationsCriterion],
            limit: Optional[int] = None) -> Iterator[common_pb2.Configuration]:
        """
        Convenience generator that transparently pages through all queryConfigurations() results, following the
        nextPageToken until the results are exhausted.  Yields individual Configuration records.

        Raises RuntimeError if any page returns an error, so callers can distinguish failure from an empty result set.

        :param criteria: List of QueryConfigurationsCriterion objects (see ConfigurationQuery helpers).
        :param limit: Maximum number of records to return per page (optional).
        :return: An iterator over all matching Configuration records across all pages.
        """
        page_token: Optional[str] = None
        while True:
            result = self.query_configurations(criteria, limit=limit, page_token=page_token)
            if result.result_status.is_error:
                raise RuntimeError(f"queryConfigurations failed during paging: {result.result_status.message}")

            for configuration in result.configurations:
                yield configuration

            page_token = result.next_page_token
            if not page_token:
                break

    # ------------------------------------------------------------------
    # deleteConfiguration
    # ------------------------------------------------------------------

    def _build_delete_configuration_request(
            self, configuration_name: str) -> annotation_pb2.DeleteConfigurationRequest:
        """
        Builds a DeleteConfigurationRequest for the supplied configuration name.
        :param configuration_name: Configuration name to delete.
        :return: A DeleteConfigurationRequest for the specified name.
        """
        self.logger.debug("Building DeleteConfigurationRequest for: %s", configuration_name)
        request = annotation_pb2.DeleteConfigurationRequest()
        request.configurationName = configuration_name
        return request

    def _send_delete_configuration(
            self, request: annotation_pb2.DeleteConfigurationRequest) -> DeleteConfigurationApiResult:
        """
        Invokes the deleteConfiguration() API method with the supplied request.
        :param request: DeleteConfigurationRequest with parameters for the call.
        :return: A DeleteConfigurationApiResult with the method response and status information.
        """
        self.logger.info("Calling deleteConfiguration API for: %s", request.configurationName)

        try:
            self.logger.debug("Invoking stub.deleteConfiguration with request")
            response = self._stub.deleteConfiguration(request)
            self.logger.debug("Received response from deleteConfiguration API")

            if response.HasField('exceptionalResult'):
                error_msg = response.exceptionalResult.message
                self.logger.warning("DeleteConfiguration API returned business error: %s", error_msg)
                return DeleteConfigurationApiResult(is_error=True, message=error_msg)

            elif response.HasField('deleteConfigurationResult'):
                self.logger.info("Successfully deleted configuration: %s", request.configurationName)
                return DeleteConfigurationApiResult(is_error=False, message="", response=response)

            else:
                error_msg = ("Unexpected response format: neither exceptionalResult nor "
                             "deleteConfigurationResult found")
                self.logger.error(error_msg)
                return DeleteConfigurationApiResult(is_error=True, message=error_msg)

        except grpc.RpcError as e:
            error_msg = f"gRPC error: {e.details()}"
            self.logger.error("gRPC error during deleteConfiguration: %s", e.details())
            return DeleteConfigurationApiResult(is_error=True, message=error_msg)
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            self.logger.error("Unexpected error during deleteConfiguration: %s", str(e), exc_info=True)
            return DeleteConfigurationApiResult(is_error=True, message=error_msg)

    def delete_configuration(self, configuration_name: str) -> DeleteConfigurationApiResult:
        """
        User-facing method for invoking the deleteConfiguration() API method.
        :param configuration_name: Configuration name to delete.
        :return: A DeleteConfigurationApiResult with the method response and status information.
        """
        self.logger.info("Starting deleteConfiguration operation for: %s", configuration_name)

        request = self._build_delete_configuration_request(configuration_name)
        result = self._send_delete_configuration(request)

        if result.result_status.is_error:
            self.logger.error("DeleteConfiguration operation failed: %s", result.result_status.message)
        else:
            self.logger.info("DeleteConfiguration operation completed successfully for: %s", configuration_name)

        return result
