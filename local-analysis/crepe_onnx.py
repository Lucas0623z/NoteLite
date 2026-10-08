"""Local CPU implementation of the official CREPE tiny model in ONNX.

Architecture, frame normalization and local weighted-bin decoding follow
https://github.com/marl/crepe/blob/c9b71ce61491454125a0693f584f7244f29d9884/crepe/core.py (MIT).
Weights are the official model-tiny.h5 from the pinned upstream models commit.
"""
from pathlib import Path
import numpy as np


def convert(weights: Path, output: Path) -> None:
    import h5py
    import onnx
    from onnx import helper as h, numpy_helper as nh, TensorProto as T
    nodes, initializers = [], []

    def tensor(name, value):
        initializers.append(nh.from_array(np.asarray(value), name))
        return name

    with h5py.File(weights, "r") as source:
        def weight(layer, key):
            group = source[layer]
            group = group[next(iter(group.keys()))]
            return np.array(group[key+":0"], dtype=np.float32)

        shape = tensor("input_shape", np.array([-1, 1, 1024, 1], dtype=np.int64))
        nodes.append(h.make_node("Reshape", ["frames", shape], ["reshape"]))
        last = "reshape"
        for index in range(1, 7):
            conv, bn = f"conv{index}", f"conv{index}-BN"
            kernel = tensor(conv+"_kernel", weight(conv, "kernel").transpose(3, 2, 0, 1))
            bias = tensor(conv+"_bias", weight(conv, "bias"))
            nodes.append(h.make_node("Conv", [last, kernel, bias], [conv],
                                     auto_pad="SAME_UPPER", strides=[4 if index == 1 else 1, 1]))
            nodes.append(h.make_node("Relu", [conv], [conv+"_relu"]))
            values = [tensor(bn+"_"+key, weight(bn, key)) for key in ("gamma", "beta", "moving_mean", "moving_variance")]
            nodes.append(h.make_node("BatchNormalization", [conv+"_relu"]+values, [bn], epsilon=.001))
            last = conv+"_pool"
            nodes.append(h.make_node("MaxPool", [bn], [last], kernel_shape=[2, 1], strides=[2, 1]))
        nodes.append(h.make_node("Transpose", [last], ["keras_flatten_order"], perm=[0, 3, 2, 1]))
        nodes.append(h.make_node("Flatten", ["keras_flatten_order"], ["flatten"], axis=1))
        kernel = tensor("classifier_kernel", weight("classifier", "kernel"))
        bias = tensor("classifier_bias", weight("classifier", "bias"))
        nodes.append(h.make_node("Gemm", ["flatten", kernel, bias], ["logits"]))
        nodes.append(h.make_node("Sigmoid", ["logits"], ["salience"]))
    graph = h.make_graph(nodes, "official-crepe-tiny", [h.make_tensor_value_info("frames", T.FLOAT, [None, 1024])],
                         [h.make_tensor_value_info("salience", T.FLOAT, [None, 360])], initializers)
    model = h.make_model(graph, producer_name="NoteLite official CREPE tiny conversion", opset_imports=[h.make_opsetid("", 13)])
    model.ir_version = 8
    onnx.checker.check_model(model)
    onnx.save(model, output)


def track(audio, sample_rate, model: Path, hop_ms=10):
    import onnxruntime as ort
    import resampy
    audio = np.asarray(audio, dtype=np.float32)
    if sample_rate != 16000:
        audio = resampy.resample(audio, sample_rate, 16000)
    audio = np.pad(audio, 512)
    hop = int(16000*hop_ms/1000)
    frames = np.lib.stride_tricks.sliding_window_view(audio, 1024)[::hop].copy()
    rms = np.sqrt(np.mean(frames*frames, axis=1))
    frames -= frames.mean(axis=1, keepdims=True)
    frames /= np.maximum(frames.std(axis=1, keepdims=True), 1e-8)
    options = ort.SessionOptions(); options.intra_op_num_threads = 2
    session = ort.InferenceSession(str(model), sess_options=options, providers=["CPUExecutionProvider"])
    activation = np.concatenate([session.run(["salience"], {"frames": frames[i:i+128]})[0] for i in range(0, len(frames), 128)])
    mapping = np.linspace(0, 7180, 360)+1997.3794084376191
    centers = activation.argmax(axis=1)
    cents = np.empty(len(centers))
    for i, center in enumerate(centers):
        low, high = max(0, center-4), min(360, center+5)
        weights = activation[i, low:high]
        cents[i] = np.dot(weights, mapping[low:high])/max(float(weights.sum()), 1e-12)
    frequency = 10*2**(cents/1200)
    confidence = activation.max(axis=1)
    confidence[rms < .008] = 0
    return np.arange(len(confidence))*hop_ms/1000, frequency, confidence
