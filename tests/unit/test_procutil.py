from esp32_sim_mcp.procutil import PortAllocator


def test_ports_are_unique_while_held():
    a = PortAllocator()
    ports = [a.allocate() for _ in range(20)]
    assert len(set(ports)) == 20
    a.release(ports[0])
    assert ports[0] not in a._held
