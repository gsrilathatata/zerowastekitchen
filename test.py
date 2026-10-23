import modal

app = modal.App("test-zerowastekitchen")

@app.function(gpu="T4")
def hello():
    import torch
    return f"GPU available: {torch.cuda.is_available()}, Device: {torch.cuda.get_device_name(0)}"

@app.local_entrypoint()
def main():
    result = hello.remote()
    print(result)