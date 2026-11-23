class Resource:

    def __init__(self, name, quantity, energy_value):

        self.name = name
        self.quantity = quantity
        self.energy_value = energy_value

    def consume(self, amount):

        if amount > self.quantity:
            amount = self.quantity

        self.quantity -= amount

        return amount * self.energy_value

    def display_info(self):

        print(f"{self.name}: {self.quantity} units")
