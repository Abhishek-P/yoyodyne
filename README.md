# Yoyodyne 🪀

[![PyPI
version](https://badge.fury.io/py/yoyodyne.svg)](https://pypi.org/project/yoyodyne)
[![Supported Python
versions](https://img.shields.io/pypi/pyversions/yoyodyne.svg)](https://pypi.org/project/yoyodyne)
[![CircleCI](https://circleci.com/gh/CUNY-CL/yoyodyne/tree/master.svg?style=svg&circle-token=37883deeb03d32c8a7b2aa7c34e5143bf514acdd)](https://circleci.com/gh/CUNY-CL/yoyodyne/tree/master)

Yoyodyne provides neural models for small-vocabulary sequence-to-sequence
generation with and without feature conditioning.

These models are implemented using [PyTorch](https://pytorch.org/) and
[Lightning](https://www.pytorchlightning.ai/).

While we provide classic `lstm` and `transformer` models, some of the provided
models are particularly well-suited for problems where the source-target
alignments are roughly monotonic (e.g., `transducer`) and/or where source and
target vocabularies have substantial overlap (e.g., `pointer_generator_lstm`).

## Philosophy

Yoyodyne is inspired by [FairSeq](https://github.com/facebookresearch/fairseq)
but differs on several key points of design:

-   It is for small-vocabulary sequence-to-sequence generation, and therefore
    includes no affordances for machine translation or language modeling.
    Because of this:
    -   It has no plugin interface and the architectures provided are intended
        to be reasonably exhaustive.
    -   There is little need for data preprocessing; it works with TSV files.
-   It has support for using features to condition decoding, with
    architecture-specific code to handle feature information.
-   🚧 UNDER CONSTRUCTION 🚧: It has exhaustive test suites.
-   🚧 UNDER CONSTRUCTION 🚧: It has performance benchmarks.
-   🚧 UNDER CONSTRUCTION 🚧: Releases are made regularly.
-   It uses validation accuracy (not loss) for model selection and early
    stoppping.

## Install

First install dependencies:

    pip install -r requirements.txt

Then install:

    pip install .

It can then be imported like a regular Python module:

```python
import yoyodyne
```

## Usage

See [`yoyodyne-predict --help`](yoyodyne/predict.py) and
[`yoyodyne-train --help`](yoyodyne/train.py).

## Data format

The default data format is a two-column TSV file in which the first column is
the source string and the second the target string.

    source   target

To enable the use of a feature column, one specifies a (non-zero) argument to
`--features-col`. For instance in the SIGMORPHON 2017 shared task, the first
column is the source (a lemma), the second is the target (the inflection), and
the third contains semi-colon delimited feature strings:

    source   target    feat1;feat2;...

this format is specified by `--features-col 3`.

Alternatively, for the SIGMORPHON 2016 shared task data format:

    source   feat1,feat2,...    target

this format is specified by `--features-col 2 --features-sep , --target-col 3`.

## Reserved symbols

Yoyodyne reserves symbols of the form `<...>` for internal use.
Feature-conditioned models also use `[...]` to avoid clashes between feature
symbols and source and target symbols. Therefore, users should not provide any
symbols of form `<...>` or `[...]`.

## Acceleration

[Hardware
accelerators](https://pytorch-lightning.readthedocs.io/en/stable/extensions/accelerator.html)
can be used during training or prediction. In addition to CPU (the default) and
GPU (`--accelerator gpu`), Yoyodyne also supports proprietary ASICs such as
TPUs.

## Architectures

The user specifies the model using the `--arch` flag (and in some cases
additional flags).

-   `attentive_lstm`: This is an LSTM encoder-decoder, with the initial hidden
    state treated as a learned parameter, and the encoder connected to the
    decoder by an attention mechanism.
-   `feature_invariant_transformer`: This is a variant of the `transformer`
    which uses a learned embedding to distinguish input symbols from features.
    It may be superior to the vanilla transformer when using features.
-   `lstm`: This is similar to the attentive LSTM, but instead of an attention
    mechanism, the last non-padding hidden state of the encoder is concatenated
    with the decoder hidden state.
-   `pointer_generator_lstm`: This is an attentive pointer-generator with an
    LSTM backend. Since this model contains a copy mechanism, it may be superior
    to the `lstm` when the input and output vocabularies overlap significantly.
-   `transducer`: This is a transducer with an LSTM backend. On model creation,
    expectation maximization is used to learn a sequence of edit operations, and
    imitation learning is used to train the model to implement the oracle
    policy, with roll-in controlled by the `--oracle-factor` flag (default: 1).
    Since this model assumes monotonic alignment, it may be superior to
    attentive models when the alignment between input and output is roughly
    monotonic and when input and output vocabularies overlap significantly.
-   `transformer`: This is a transformer encoder-decoder with positional
    encoding and layer normalization. The user may wish to specify the number of
    attention heads (with `--attention-heads`; default: 4).

For all models, the user may also wish to specify:

-   `--decoder_layers` (default: 1): number of decoder layers
-   `--embedding` (default: 128): embedding size
-   `--encoder_layers` (default: 1): number of encoder layers
-   `--hidden_size` (default: 512): hidden layer size

By default, the `lstm`, `pointer_generator_lstm`, and `transducer` models use an
LSTM bidirectional encoder. One can disable this with the `--no_bidirectional`
flag.

## Training options

A non-exhaustive list includes:

-   Batch size:
    -   `--batch_size` (default: 32)
-   Regularization:
    -   `--dropout` (default: .2)
    -   `--label_smoothing` (default: not enabled)
    -   `--gradient_clip_val` (default: not enabled)
-   Optimizer:
    -   `--learning_rate` (default: .001)
    -   `--optimizer` (default: "adam")
    -   `--beta1` (default: .9): $\beta_1$ hyperparameter for the Adam optimizer
        (`--optimizer adam`)
    -   `--beta2` (default: .99): $\beta_2$ hyperparameter for the Adam
        optimizer (`--optimizer adam`)
    -   `--scheduler` (default: not enabled)
    -   `--warmup_steps` (default: not enabled): warm-up parameter for a linear
        warm-up followed by inverse square root decay schedule (only valid with
        `--scheduler warmupinvsqrt`)
-   Duration:
    -   `--max_epochs`
    -   `--min_epochs`
    -   `--max_steps`
    -   `--min_steps`
    -   `--max_time`
    -   `--patience`
-   Seeding:
    -   `--seed`
-   [Weights & Biases](https://wandb.ai/site)
    -   `--wandb` (default: False): enables Weights & Biases tracking.

**No neural model should be deployed without proper hyperparameter tuning.**
However, the default options give a reasonable initial settings for an attentive
biLSTM. For transformer-based architectures, experiment with multiple encoder
and decoder layers, much larger batches, and the warmup-plus-inverse square root
decay scheduler.

## Accelerators

By default Yoyodyne runs on CPU. One can specify accelerators using the
`--accelerators` flag. For instance `--accelerators gpu` will use a local
CUDA-enabled GPU. [Other
accelerators](https://pytorch-lightning.readthedocs.io/en/stable/extensions/accelerator.html)
may also be supported but not all have been tested yet.
