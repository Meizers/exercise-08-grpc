from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Empty(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class RegisterRequest(_message.Message):
    __slots__ = ("name", "host", "port")
    NAME_FIELD_NUMBER: _ClassVar[int]
    HOST_FIELD_NUMBER: _ClassVar[int]
    PORT_FIELD_NUMBER: _ClassVar[int]
    name: str
    host: str
    port: int
    def __init__(self, name: _Optional[str] = ..., host: _Optional[str] = ..., port: _Optional[int] = ...) -> None: ...

class GetRequest(_message.Message):
    __slots__ = ("name",)
    NAME_FIELD_NUMBER: _ClassVar[int]
    name: str
    def __init__(self, name: _Optional[str] = ...) -> None: ...

class UpdateRequest(_message.Message):
    __slots__ = ("name", "host", "port")
    NAME_FIELD_NUMBER: _ClassVar[int]
    HOST_FIELD_NUMBER: _ClassVar[int]
    PORT_FIELD_NUMBER: _ClassVar[int]
    name: str
    host: str
    port: int
    def __init__(self, name: _Optional[str] = ..., host: _Optional[str] = ..., port: _Optional[int] = ...) -> None: ...

class DeleteRequest(_message.Message):
    __slots__ = ("name",)
    NAME_FIELD_NUMBER: _ClassVar[int]
    name: str
    def __init__(self, name: _Optional[str] = ...) -> None: ...

class NodeResponse(_message.Message):
    __slots__ = ("id", "name", "host", "port", "status", "created_at", "updated_at")
    ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    HOST_FIELD_NUMBER: _ClassVar[int]
    PORT_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    UPDATED_AT_FIELD_NUMBER: _ClassVar[int]
    id: int
    name: str
    host: str
    port: int
    status: str
    created_at: str
    updated_at: str
    def __init__(self, id: _Optional[int] = ..., name: _Optional[str] = ..., host: _Optional[str] = ..., port: _Optional[int] = ..., status: _Optional[str] = ..., created_at: _Optional[str] = ..., updated_at: _Optional[str] = ...) -> None: ...

class NodeList(_message.Message):
    __slots__ = ("nodes",)
    NODES_FIELD_NUMBER: _ClassVar[int]
    nodes: _containers.RepeatedCompositeFieldContainer[NodeResponse]
    def __init__(self, nodes: _Optional[_Iterable[_Union[NodeResponse, _Mapping]]] = ...) -> None: ...

class HealthResponse(_message.Message):
    __slots__ = ("status", "db", "nodes_count")
    STATUS_FIELD_NUMBER: _ClassVar[int]
    DB_FIELD_NUMBER: _ClassVar[int]
    NODES_COUNT_FIELD_NUMBER: _ClassVar[int]
    status: str
    db: str
    nodes_count: int
    def __init__(self, status: _Optional[str] = ..., db: _Optional[str] = ..., nodes_count: _Optional[int] = ...) -> None: ...
