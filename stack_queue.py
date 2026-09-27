# stack_queue.py - Cai dat Stack va Queue BANG CLASS

class Stack:
    """Ngan xep: Vao sau ra truoc (LIFO)"""
    def __init__(self):
        self.data = []

    def push(self, x):
        self.data.append(x)

    def pop(self):
        if self.is_empty():
            raise IndexError("Stack rong!")
        return self.data.pop()

    def peek(self):
        if self.is_empty():
            raise IndexError("Stack rong!")
        return self.data[-1]

    def top(self):
        return self.peek()

    def is_empty(self):
        return len(self.data) == 0

    def size(self):
        return len(self.data)

    def display(self):
        print("Stack (dinh -> day):", list(reversed(self.data)))


class Queue:
    """Hang doi: Vao truoc ra truoc (FIFO)"""
    def __init__(self):
        self.data = []

    def enqueue(self, x):
        self.data.append(x)

    def dequeue(self):
        if self.is_empty():
            raise IndexError("Queue rong!")
        return self.data.pop(0)

    def front(self):
        if self.is_empty():
            raise IndexError("Queue rong!")
        return self.data[0]

    def rear(self):
        if self.is_empty():
            raise IndexError("Queue rong!")
        return self.data[-1]

    def is_empty(self):
        return len(self.data) == 0

    def size(self):
        return len(self.data)

    def display(self):
        print("Queue (dau -> cuoi):", self.data)
