# main.py - Chuong trinh chinh, DUNG CLASS Stack/Queue
# 1) Doi he THAP PHAN (10) <-> NHI PHAN (2)
# 2) Doi trung to -> hau to
# 3) Tinh hau to
from stack_queue import Stack, Queue


class ChuyenDoiHeDem:
    """Lop xu ly doi he dem, ben trong DUNG Stack."""
    @staticmethod
    def thap_phan_sang_nhi_phan(n):
        if n == 0:
            return "0"
        am = n < 0
        n = abs(n)
        s = Stack()
        while n > 0:
            s.push(n % 2)
            n //= 2
        kq = ""
        while not s.is_empty():
            kq += str(s.pop())
        return "-" + kq if am else kq

    @staticmethod
    def nhi_phan_sang_thap_phan(chuoi):
        chuoi = chuoi.strip()
        am = chuoi.startswith("-")
        if am:
            chuoi = chuoi[1:]
        if not chuoi or any(c not in "01" for c in chuoi):
            raise ValueError("Chuoi nhi phan chi gom 0 va 1!")
        gt = 0
        for c in chuoi:
            gt = gt * 2 + int(c)
        return -gt if am else gt


class BieuThuc:
    """Lop xu ly bieu thuc, ben trong DUNG Stack."""
    @staticmethod
    def uu_tien(op):
        if op in ('+', '-'):
            return 1
        if op in ('*', '/', '%'):
            return 2
        if op == '^':
            return 3
        return 0

    @staticmethod
    def trung_to_sang_hau_to(bt):
        s = Stack()
        kq = []
        i = 0
        while i < len(bt):
            c = bt[i]
            if c == ' ':
                i += 1
                continue
            if c.isdigit() or c == '.':
                so = ""
                while i < len(bt) and (bt[i].isdigit() or bt[i] == '.'):
                    so += bt[i]
                    i += 1
                kq.append(so)
                continue
            elif c == '(':
                s.push(c)
            elif c == ')':
                while not s.is_empty() and s.peek() != '(':
                    kq.append(s.pop())
                if s.is_empty():
                    raise ValueError("Thieu '('")
                s.pop()
            else:
                while (not s.is_empty() and s.peek() != '(' and
                       (BieuThuc.uu_tien(s.peek()) > BieuThuc.uu_tien(c) or
                        (BieuThuc.uu_tien(s.peek()) == BieuThuc.uu_tien(c) and c != '^'))):
                    kq.append(s.pop())
                s.push(c)
            i += 1
        while not s.is_empty():
            if s.peek() == '(':
                raise ValueError("Thieu ')'")
            kq.append(s.pop())
        return ' '.join(kq)

    @staticmethod
    def tinh_hau_to(hau_to):
        s = Stack()
        for token in hau_to.split():
            if token.replace('.', '', 1).lstrip('-').isdigit():
                s.push(float(token) if '.' in token else int(token))
            else:
                b = s.pop()
                a = s.pop()
                if token == '+':
                    s.push(a + b)
                elif token == '-':
                    s.push(a - b)
                elif token == '*':
                    s.push(a * b)
                elif token == '/':
                    s.push(a / b)
                elif token == '%':
                    s.push(a % b)
                elif token == '^':
                    s.push(a ** b)
                else:
                    raise ValueError("Toan tu la: " + token)
        if s.size() != 1:
            raise ValueError("Bieu thuc hau to khong hop le!")
        kq = s.pop()
        if isinstance(kq, float) and kq.is_integer():
            kq = int(kq)
        return kq


def demo_co_ban():
    print("\n--- DEMO STACK (LIFO) ---")
    st = Stack()
    for x in [1, 2, 3]:
        st.push(x)
        print(f"push({x}) -> ", end="")
        st.display()
    while not st.is_empty():
        print(f"pop() -> {st.pop()}, con lai: {st.data}")
    print("\n--- DEMO QUEUE (FIFO) ---")
    q = Queue()
    for x in [1, 2, 3]:
        q.enqueue(x)
        print(f"enqueue({x}) -> ", end="")
        q.display()
    while not q.is_empty():
        print(f"dequeue() -> {q.dequeue()}, con lai: {q.data}")


def menu():
    while True:
        print("\n===== STACK / QUEUE (100% CLASS) =====")
        print("0. Demo LIFO/FIFO")
        print("1. He THAP PHAN (10) -> NHI PHAN (2)")
        print("2. He NHI PHAN (2) -> THAP PHAN (10)")
        print("3. Trung to -> Hau to")
        print("4. Tinh hau to")
        print("5. Trung to -> Hau to -> Tinh luon")
        print("6. Thoat")
        chon = input("Moi chon (0-6): ").strip()
        if chon == "0":
            demo_co_ban()
        elif chon == "1":
            n = int(input("Nhap so he thap phan (10): "))
            print(f"{n} (thap phan) = {ChuyenDoiHeDem.thap_phan_sang_nhi_phan(n)} (nhi phan)")
        elif chon == "2":
            b = input("Nhap so he nhi phan (2): ")
            try:
                print(f"{b} (nhi phan) = {ChuyenDoiHeDem.nhi_phan_sang_thap_phan(b)} (thap phan)")
            except Exception as e:
                print("Loi:", e)
        elif chon == "3":
            bt = input("Nhap trung to (vd: (3+4)*2-7): ")
            try:
                print("Hau to:", BieuThuc.trung_to_sang_hau_to(bt))
            except Exception as e:
                print("Loi:", e)
        elif chon == "4":
            bt = input("Nhap hau to (vd: 3 4 + 2 *): ")
            try:
                print("Ket qua:", BieuThuc.tinh_hau_to(bt))
            except Exception as e:
                print("Loi:", e)
        elif chon == "5":
            bt = input("Nhap trung to (vd: (3+4)*2): ")
            try:
                hau = BieuThuc.trung_to_sang_hau_to(bt)
                print("Hau to:", hau)
                print("Ket qua:", BieuThuc.tinh_hau_to(hau))
            except Exception as e:
                print("Loi:", e)
        elif chon == "6":
            break
        else:
            print("Chon sai!")


if __name__ == "__main__":
    menu()
