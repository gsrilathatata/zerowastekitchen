import modal

app = modal.App("test-zerowastekitchen")

image = modal.Image.debian_slim().pip_install("torch", "numpy")

@app.function(gpu="T4", image=image)
def hello():
    import torch
    result = f"GPU available: {torch.cuda.is_available()}"
    if torch.cuda.is_available():
        result += f", Device: {torch.cuda.get_device_name(0)}"
    print(result)
    return result

@app.local_entrypoint()
def main():
    result = hello.remote()
    print(f"Result: {result}")