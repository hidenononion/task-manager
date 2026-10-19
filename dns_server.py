import socket
import struct
import threading
import sys

DNS_HOST = '0.0.0.0'
DNS_PORT = 53
UPSTREAM_DNS = '8.8.8.8'
UPSTREAM_PORT = 53

DOMAIN_MAP = {
    'dtnlamkhe.com': '192.168.0.102',
    'dtnlamkhe': '192.168.0.102',
}


def parse_domain_name(data, offset):
    parts = []
    while offset < len(data):
        length = data[offset]
        if length == 0:
            offset += 1
            break
        offset += 1
        parts.append(data[offset:offset + length].decode('utf-8', errors='replace'))
        offset += length
    return '.'.join(parts), offset


def build_dns_response(query_data, resolved_ip):
    tx_id = query_data[:2]
    flags = b'\x81\x80'
    questions = struct.pack('>H', 1)
    answers_rr = struct.pack('>H', 1)
    authority_rr = struct.pack('>H', 0)
    additional_rr = struct.pack('>H', 0)
    header = tx_id + flags + questions + answers_rr + authority_rr + additional_rr

    question_section = query_data[12:]
    name_end = question_section.find(b'\x00') + 1
    qname = question_section[:name_end + 4]

    ip_parts = [int(p) for p in resolved_ip.split('.')]
    rdata = bytes(ip_parts)
    answer = b'\xc0\x0c'
    answer += struct.pack('>HHIH', 1, 1, 300, len(rdata))
    answer += rdata

    return header + qname + answer


def handle_query(data, addr, sock):
    try:
        offset = 12
        domain, _ = parse_domain_name(data, offset)

        if domain in DOMAIN_MAP:
            ip = DOMAIN_MAP[domain]
            response = build_dns_response(data, ip)
            sock.sendto(response, addr)
        else:
            upstream = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            upstream.settimeout(3)
            try:
                upstream.sendto(data, (UPSTREAM_DNS, UPSTREAM_PORT))
                response, _ = upstream.recvfrom(512)
                sock.sendto(response, addr)
            except Exception:
                pass
            finally:
                upstream.close()
    except Exception as e:
        pass


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((DNS_HOST, DNS_PORT))
    except OSError as e:
        print(f'[DNS] Loi bind port {DNS_PORT}: {e}')
        print('[DNS] Kiem tra Windows DNS Client service dang chay tren port 53!')
        print('[DNS] Goi "net stop dnscache" voi quyen Admin de dung hoac doi port.')
        sys.exit(1)

    print(f'[DNS] Dang lang nghe tren {DNS_HOST}:{DNS_PORT}')
    print(f'[DNS] Resolve: dtnlamkhe.com -> 192.168.1.19')
    print(f'[DNS] Forward: * -> {UPSTREAM_DNS}')

    while True:
        try:
            data, addr = sock.recvfrom(512)
            t = threading.Thread(target=handle_query, args=(data, addr, sock), daemon=True)
            t.start()
        except KeyboardInterrupt:
            break
        except Exception:
            pass

    sock.close()


if __name__ == '__main__':
    main()
