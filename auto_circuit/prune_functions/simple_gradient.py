from typing import Dict, Set

import torch as t
from torch.nn.functional import log_softmax
from torch.utils.data import DataLoader

from auto_circuit.data import PromptPairBatch
from auto_circuit.types import Edge
from auto_circuit.utils.graph_utils import (
    get_sorted_src_outs,
    patch_mode,
    train_mask_mode,
)


def simple_gradient_prune_scores(
    model: t.nn.Module,
    train_data: DataLoader[PromptPairBatch],
) -> Dict[Edge, float]:
    """Prune scores are the integrated gradient of each edge."""
    edges: Set[Edge] = model.edges  # type: ignore
    out_slice = model.out_slice

    src_outs_dict: Dict[int, t.Tensor] = {}
    for batch in train_data:
        patch_outs = get_sorted_src_outs(model, batch.clean)
        src_outs_dict[batch.key] = t.stack(list(patch_outs.values()))

    with train_mask_mode(model):
        for batch in train_data:
            patch_src_outs = src_outs_dict[batch.key].clone().detach()
            with patch_mode(model, t.zeros_like(patch_src_outs), patch_src_outs):
                masked_logprobs = log_softmax(model(batch.corrupt)[out_slice], dim=-1)
                answer_probs = t.gather(
                    masked_logprobs, dim=1, index=batch.answers
                ).squeeze(-1)
                loss = answer_probs.mean()
                loss.backward()

    prune_scores = {}
    for edge in edges:
        grad = edge.patch_mask(model).grad
        assert grad is not None
        prune_scores[edge] = grad[edge.patch_idx].abs()
    return prune_scores
