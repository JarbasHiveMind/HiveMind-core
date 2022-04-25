from jarbas_hive_mind.configuration import CONFIGURATION

if CONFIGURATION['twisted']:
    try:
        from jarbas_hive_mind.backends.twisted_reactor import WebSocketServerProtocol,\
            WebSocketServerFactory, WebSocketClientFactory, WebSocketClientProtocol,\
            HiveMindTwistedListener as HiveMindListener, \
            HiveMindTwistedConnection as HiveMindConnection
    except ImportError:
        # only asyncio available / twisted not installed
        CONFIGURATION['twisted'] = False

if not CONFIGURATION['twisted']:
    from jarbas_hive_mind.backends.asyncio_loop import WebSocketServerProtocol,\
        WebSocketServerFactory, WebSocketClientFactory, WebSocketClientProtocol,\
        HiveMindAsyncioListener as HiveMindListener, \
        HiveMindAsyncioConnection as HiveMindConnection

