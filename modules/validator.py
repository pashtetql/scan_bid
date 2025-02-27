import subprocess

from requests import post


class KeyValidator:
    KEYSERVER_BASE_URL = 'http://45.144.31.69:5000'

    def __init__(self, product_name, license_key):
        self.hardware_id = None
        self.product_name = product_name
        self.license_key = license_key

    def read_hardware_id(self) -> bool:
        id_command = 'powershell.exe -Command "Get-WmiObject Win32_ComputerSystemProduct | Select-Object -ExpandProperty UUID"'
        try:
            pc_id = subprocess.check_output(id_command).decode('utf-8').strip()
        except Exception:
            print('something is wrong with your OS. You should run this on Windows with powershell installed')
            return False

        if pc_id == '':
            print('something is wrong with your OS. You should run this on Windows with powershell installed')

        self.hardware_id = pc_id
        return True

    def suggest_register_id(self) -> bool:
        print("this license isn't bound to any pc yet")
        answer = input('do you want to register this pc for this license?[yes/no]: ')
        match answer:
            case 'yes':
                response = post(
                    url=f"{self.KEYSERVER_BASE_URL}/register-hardware",
                    json={
                        'license_key': self.license_key,
                        'product_name': self.product_name,
                        'hardware_id': self.hardware_id
                    }
                )

                if response.status_code != 200:
                    print(response.text)
                    return False

                print('successfully registered')
                return True
            case 'no':
                print('ok, terminating program')
                return False
            case _:
                print('invalid option, terminating program')
                return False

    def check_key(self) -> bool:
        response = post(
            url=f"{self.KEYSERVER_BASE_URL}/check-key",
            json={
                'license_key': self.license_key,
                'product_name': self.product_name,
                'hardware_id': self.hardware_id
            }
        )

        if response.status_code != 200:
            print(response.text)
            return False

        if response.json()['result'] == 'OK':
            return True

        return self.suggest_register_id()

