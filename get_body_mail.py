import requests

url = "https://email.muaxu.vn/get.php"

r = requests.get(
    url,
    params={
        "email": "elizabethreed595@borstonlinemanagement.com"
    },
    timeout=10
)

print(r.json())