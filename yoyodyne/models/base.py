"""Base model class, with PL integration.

This also includes init_embeddings, which has to go somewhere.
"""

import argparse
from typing import Callable, Dict, Optional

import pytorch_lightning as pl
import torch
from torch import nn, optim

from .. import batches, evaluators, schedulers, util


class BaseEncoderDecoder(pl.LightningModule):

    # Indices.
    pad_idx: int
    start_idx: int
    end_idx: int
    # Sizes.
    vocab_size: int
    output_size: int
    # Optimizer arguments.
    beta1: float
    beta2: float
    optimizer: str
    scheduler: Optional[str]
    warmup_steps: int
    # Regularization arguments.
    dropout: float
    label_smoothing: Optional[float]
    # Decoding arguments.
    beam_width: int
    max_decode_length: int
    # Model arguments.
    decoder_layers: int
    embedding_size: int
    encoder_layers: int
    hidden_size: int
    # Constructed inside __init__.
    dropout_layer: nn.Dropout
    evaluator: evaluators.Evaluator
    loss_func: Callable[[torch.Tensor, torch.Tensor], torch.Tensor]

    def __init__(
        self,
        *,
        pad_idx,
        start_idx,
        end_idx,
        vocab_size,
        output_size,
        beta1=0.9,
        beta2=0.999,
        learning_rate=0.001,
        optimizer="adam",
        scheduler=None,
        warmup_steps=0,
        dropout=0.2,
        label_smoothing=None,
        beam_width=1,
        max_decode_length=128,
        decoder_layers=1,
        embedding_size=128,
        encoder_layers=1,
        hidden_size=512,
        dataset=None,
        **kwargs,  # Ignored.
    ):
        self.dataset = dataset
        # Saves hyperparameters for PL checkpointing.
        super().__init__()
        self.pad_idx = pad_idx
        self.start_idx = start_idx
        self.end_idx = end_idx
        self.vocab_size = vocab_size
        self.output_size = output_size
        self.beta1 = beta1
        self.beta2 = beta2
        self.learning_rate = learning_rate
        self.optimizer = optimizer
        self.scheduler = scheduler
        self.warmup_steps = warmup_steps
        self.dropout = dropout
        self.label_smoothing = label_smoothing
        self.beam_width = beam_width
        self.max_decode_length = max_decode_length
        self.decoder_layers = decoder_layers
        self.embedding_size = embedding_size
        self.encoder_layers = encoder_layers
        self.hidden_size = hidden_size
        self.dropout_layer = nn.Dropout(p=self.dropout, inplace=False)
        self.evaluator = evaluators.Evaluator()
        self.loss_func = self.get_loss_func("mean")
        # Saves hyperparameters for PL checkpointing.
        self.save_hyperparameters(ignore=["dataset"])

    @staticmethod
    def _xavier_embedding_initialization(
        num_embeddings: int, embedding_size: int, pad_idx: int
    ) -> nn.Embedding:
        """Initializes the embeddings layer using Xavier initialization.

        The pad embeddings are also zeroed out.

        Args:
            num_embeddings (int): number of embeddings.
            embedding_size (int): dimension of embeddings.
            pad_idx (int): index of pad symbol.

        Returns:
            nn.Embedding: embedding layer.
        """
        embedding_layer = nn.Embedding(num_embeddings, embedding_size)
        # Xavier initialization.
        nn.init.normal_(
            embedding_layer.weight, mean=0, std=embedding_size**-0.5
        )
        # Zeroes out pad embeddings.
        if pad_idx is not None:
            nn.init.constant_(embedding_layer.weight[pad_idx], 0.0)
        return embedding_layer

    @staticmethod
    def _normal_embedding_initialization(
        num_embeddings: int, embedding_size: int, pad_idx: int
    ) -> nn.Embedding:
        """Initializes the embeddings layer from a normal distribution.

        The pad embeddings are also zeroed out.

        Args:
            num_embeddings (int): number of embeddings.
            embedding_size (int): dimension of embeddings.
            pad_idx (int): index of pad symbol.

        Returns:
            nn.Embedding: embedding layer.
        """
        embedding_layer = nn.Embedding(num_embeddings, embedding_size)
        # Zeroes out pad embeddings.
        if pad_idx is not None:
            nn.init.constant_(embedding_layer.weight[pad_idx], 0.0)
        return embedding_layer

    @staticmethod
    def init_embeddings(
        num_embed: int, embed_size: int, pad_idx: int
    ) -> nn.Embedding:
        """Method interface for initializing the embedding layer.

        Args:
            num_embeddings (int): number of embeddings.
            embedding_size (int): dimension of embeddings.
            pad_idx (int): index of pad symbol.

        Raises:
            NotImplementedError: This method needs to be overridden.

        Returns:
            nn.Embedding: embedding layer.
        """
        raise NotImplementedError

    def training_step(
        self,
        batch: batches.PaddedBatch,
        batch_idx: int,
    ) -> torch.Tensor:
        """Runs one step of training.

        This is called by the PL Trainer.

        Args:
            batch (batches.PaddedBatch)
            batch_idx (int).

        Returns:
            torch.Tensor: loss.
        """
        print("TRAIN TRUNCATED SOURCE BATCH", list(self.dataset.decode_source(batch.source.padded))[:3], flush=True)
        print("TRAIN TRUNCATED TARGET BATCH", list(self.dataset.decode_target(batch.target.padded))[:3], flush=True)
        if batch.features:
           print("TRAIN TRUNCATED FEATURES BATCH", list(self.dataset.decode_features(batch.features.padded))[:3], flush=True)
        self.train()
        predictions = self(batch)
        target_padded = batch.target.padded
        loss = self.loss_func(predictions, target_padded)
        self.log(
            "train_loss",
            loss,
            batch_size=len(batch),
            on_step=False,
            on_epoch=True,
        )
        return loss

    def validation_step(
        self,
        batch: batches.PaddedBatch,
        batch_idx: int,
    ) -> Dict:
        """Runs one validation step.

        This is called by the PL Trainer.

        Args:
            batch (batches.PaddedBatch).
            batch_idx (int).

        Returns:
            Dict[str, float]: validation metrics.
        """
        print("EVAL TRUNCATED SOURCE BATCH", list(self.dataset.decode_source(batch.source.padded))[:10])
        print("EVAL TRUNCATED TARGET BATCH", list(self.dataset.decode_target(batch.target.padded))[:10])
        if batch.features:
            print("EVAL TRUNCATED FEATURES BATCH", list(self.dataset.decode_features(batch.features.padded))[:10])
        self.eval()
        # Greedy decoding.
        predictions = self(batch)
        target_padded = batch.target.padded
        val_eval_item = self.evaluator.evaluate(
            predictions, target_padded, self.end_idx, self.pad_idx
        )
        # We rerun the model with teacher forcing so we can compute loss.
        # TODO: Update to run the model only once.
        loss = self.loss_func(self(batch), target_padded)
        return {"val_eval_item": val_eval_item, "val_loss": loss}

    def validation_epoch_end(self, validation_step_outputs: Dict) -> Dict:
        """Computes average loss and average accuracy.

        Args:
            validation_step_outputs (Dict).

        Returns:
            Dict: averaged metrics over all validation steps.
        """
        num_steps = len(validation_step_outputs)
        avg_val_loss = (
                sum([v["val_loss"] for v in validation_step_outputs]) / num_steps
        )
        epoch_eval = sum(v["val_eval_item"] for v in validation_step_outputs)
        metrics = {
            "val_loss": avg_val_loss,
            "val_accuracy": epoch_eval.accuracy,
        }
        for metric, value in metrics.items():
            self.log(metric, value, prog_bar=True)
        return metrics

    def _get_predicted(self, predictions: torch.Tensor) -> torch.Tensor:
        """Picks the best index from the vocabulary.

        Args:
            predictions (torch.Tensor): B x seq_len x vocab_size.

        Returns:
            torch.Tensor: indices of the argmax at each timestep.
        """
        assert len(predictions.size()) == 3
        _, indices = torch.max(predictions, dim=2)
        return indices

    def configure_optimizers(self) -> optim.Optimizer:
        """Gets the configured torch optimizer.

        This is called by the PL Trainer.

        Returns:
            optim.Optimizer: optimizer for training.
        """
        optimizer = self._get_optimizer()
        scheduler = self._get_lr_scheduler(optimizer[0])
        util.log_info("Optimizer details:")
        util.log_info(optimizer)
        if scheduler:
            util.log_info("Scheduler details:")
            util.log_info(scheduler)
        return optimizer, scheduler

    def _get_optimizer(self) -> optim.Optimizer:
        """Factory for selecting the optimizer.

        Returns:
            optim.Optimizer: optimizer for training.
        """
        optim_fac = {
            "adadelta": optim.Adadelta,
            "adam": optim.Adam,
            "sgd": optim.SGD,

        }
        optimizer = optim_fac[self.optimizer]
        kwargs = {"lr": self.learning_rate}
        if self.optimizer == "adam":
            kwargs["betas"] = self.beta1, self.beta2
        return [optimizer(self.parameters(), **kwargs)]

    def _get_lr_scheduler(
        self, optimizer: optim.Optimizer
    ) -> optim.lr_scheduler:
        """Factory for selecting the scheduler.

        Args:
            optimizer (optim.Optimizer): optimizer.

        Returns:
            optim.lr_scheduler: LR scheduler for training.
        """
        if self.scheduler is None:
            return []
        # TODO: Implement multiple options.
        scheduler_fac = {
            "warmupinvsqrt": schedulers.WarmupInverseSquareRootSchedule
        }
        scheduler = scheduler_fac[self.scheduler](
            optimizer=optimizer, warmup_steps=self.warmup_steps
        )
        scheduler_cfg = {
            "scheduler": scheduler,
            "interval": "step",
            "frequency": 1,
        }
        return [scheduler_cfg]

    def get_loss_func(
        self, reduction: str
    ) -> Callable[[torch.Tensor, torch.Tensor], torch.Tensor]:
        """Returns the actual function used to compute loss.

        Args:
            reduction (str): reduction for the loss function (e.g., "mean").

        Returns:
            Callable[[torch.Tensor, torch.Tensor], torch.Tensor]: configured
                loss function.
        """
        if self.label_smoothing is None:
            return nn.NLLLoss(ignore_index=self.pad_idx, reduction=reduction)
        else:

            def _smooth_nllloss(
                predictions: torch.Tensor, target: torch.Tensor
            ) -> Callable[[torch.Tensor, torch.Tensor], torch.Tensor]:
                """After:

                    https://github.com/NVIDIA/DeepLearningExamples/blob/
                    8d8b21a933fff3defb692e0527fca15532da5dc6/PyTorch/Classification/
                    ConvNets/image_classification/smoothing.py#L18

                Args:
                    predictions (torch.Tensor): tensor of prediction
                        distribution of shape B x vocab_size x seq_len.
                    target (torch.Tensor): tensor of golds of shape
                        B x seq_len.

                Returns:
                    torch.Tensor: loss.
                """
                # -> (B * seq_len) x output_size
                predictions = predictions.transpose(1, 2).reshape(
                    -1, self.output_size
                )
                # -> (B * seq_len) x 1
                target = target.view(-1, 1)
                non_pad_mask = target.ne(self.pad_idx)
                # Gets the ordinary loss.
                nll_loss = -predictions.gather(dim=-1, index=target)[
                    non_pad_mask
                ].mean()
                # Gets the smoothed loss.
                smooth_loss = -predictions.sum(dim=-1, keepdim=True)[
                    non_pad_mask
                ].mean()
                smooth_loss = smooth_loss / self.output_size
                # Combines both according to label smoothing weight.
                loss = (1.0 - self.label_smoothing) * nll_loss
                loss += self.label_smoothing * smooth_loss
                return loss

            return _smooth_nllloss

    @staticmethod
    def add_argparse_args(parser: argparse.ArgumentParser) -> None:
        """Adds shared configuration options to the argument parser.

        These are only needed at training time.

        Args:
            parser (argparse.ArgumentParser).
        """
        # Optimizer arguments.
        parser.add_argument(
            "--beta1",
            type=float,
            default=0.9,
            help="beta_1 (Adam optimizer only). Default: %(default)s.",
        )
        parser.add_argument(
            "--beta2",
            type=float,
            default=0.999,
            help="beta_2 (Adam optimizer only). Default: %(default)s.",
        )
        parser.add_argument(
            "--learning_rate",
            type=float,
            default=0.001,
            help="Learning rate. Default: %(default)s.",
        )
        parser.add_argument(
            "--optimizer",
            choices=["adadelta", "adam", "sgd"],
            default="adam",
            help="Optimizer. Default: %(default)s.",
        )
        parser.add_argument(
            "--scheduler",
            choices=["warmupinvsqrt"],
            help="Learning rate scheduler",
        )
        parser.add_argument(
            "--warmup_steps",
            type=int,
            default=0,
            help="Number of warmup steps (warmupinvsqrt scheduler only). "
            "Default: %(default)s.",
        )
        # Regularization arguments.
        parser.add_argument(
            "--dropout",
            type=float,
            default=0.2,
            help="Dropout probability. Default: %(default)s.",
        )
        parser.add_argument(
            "--label_smoothing",
            type=float,
            help="Coefficient for label smoothing.",
        )
        # Decoding arguments.
        parser.add_argument(
            "--max_decode_length",
            type=int,
            default=128,
            help="Maximum decoder string length. Default: %(default)s.",
        )
        # TODO: add --beam_width.
        # Model arguments.
        parser.add_argument(
            "--decoder_layers",
            type=int,
            default=1,
            help="Number of decoder layers. Default: %(default)s.",
        )
        parser.add_argument(
            "--embedding_size",
            type=int,
            default=128,
            help="Dimensionality of embeddings. Default: %(default)s.",
        )
        parser.add_argument(
            "--encoder_layers",
            type=int,
            default=1,
            help="Number of encoder layers. Default: %(default)s.",
        )
        parser.add_argument(
            "--hidden_size",
            type=int,
            default=512,
            help="Dimensionality of the hidden layer(s). "
            "Default: %(default)s.",
        )
