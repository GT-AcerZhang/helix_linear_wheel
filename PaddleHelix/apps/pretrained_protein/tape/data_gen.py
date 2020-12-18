#   Copyright (c) 2020 PaddlePaddle Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
DataLoader generator for the sequence-based pretrain models for protein.
"""

import numpy as np
import paddle.fluid as fluid
from pahelix.utils.data_utils import get_part_files
from pahelix.utils.language_model_tools import apply_bert_mask
from pahelix.utils.protein_tools import ProteinTokenizer

def pretrain_sample_reader(filenames, batch_size):
    """DataLoader for pretraining tasks.

    Args:
        filenames(list): filenames of the input data.
        batch_size(int): size of the each batch.

    Returns:
        reader(func): data reader.
    """
    def __reader__():
        examples = []
        for filename in filenames:
            data = np.load(filename)
            masked_token_ids, labels = apply_bert_mask(data['token_ids'], ProteinTokenizer)
            lengths = data['lengths']

            offset = 0
            for i in range(lengths.size):
                tokens = masked_token_ids[offset:offset + lengths[i]].reshape(lengths[i], 1)
                pos = np.arange(lengths[i]).reshape(lengths[i], 1)
                label = labels[offset:offset + lengths[i]].reshape(lengths[i], 1)
                examples.append((tokens, pos, label))
                if len(examples) == batch_size:
                    yield examples
                    examples.clear()
                offset += lengths[i]
        if len(examples) > 0:
            yield examples
    return __reader__


def sequence_sample_reader(filenames, batch_size, label_name):
    """DataLoader for sequence classification/regression tasks.

    Args:
        filenames(list): filenames of the input data.
        batch_size(int): size of the each batch.
        label_name(str): label name.

    Returns:
        reader(func): data reader.
    """
    def __reader__():
        examples = []
        for filename in filenames:
            data = np.load(filename)
            token_ids = data['token_ids']
            labels = data[label_name]
            lengths = data['lengths']

            offset = 0
            for i in range(lengths.size):
                tokens = token_ids[offset:offset + lengths[i]].reshape(lengths[i], 1)
                pos = np.arange(lengths[i]).reshape(lengths[i], 1)
                label = labels[offset:offset + lengths[i]].reshape(lengths[i], 1)
                examples.append((tokens, pos, label))
                if len(examples) == batch_size:
                    yield examples
                    examples.clear()
                offset += lengths[i]
        if len(examples) > 0:
            yield examples
    return __reader__


def normal_sample_reader(filenames, batch_size, label_name):
    """DataLoader for classification/regression tasks.

    Args:
        filenames(list): filenames of the input data.
        batch_size(int): size of the each batch.
        label_name(str): label name.

    Returns:
        reader(func): data reader.
    """
    def __reader__():
        examples = []
        for filename in filenames:
            data = np.load(filename)
            token_ids = data['token_ids']
            labels = data[label_name]
            lengths = data['lengths']

            offset = 0
            for i in range(lengths.size):
                tokens = token_ids[offset:offset + lengths[i]].reshape(lengths[i], 1)
                pos = np.arange(lengths[i]).reshape(lengths[i], 1)
                label = labels[i:i + 1].reshape(1, 1)
                examples.append((tokens, pos, label))
                if len(examples) == batch_size:
                    yield examples
                    examples.clear()
                offset += lengths[i]
        if len(examples) > 0:
            yield examples
    return __reader__


def get_sample_generator(filenames, batch_size, model_config):
    """Set data loader generator according to different tasks.

    Args:
        filenames(list): filenames of the input data.
        batch_size(int): size of the each batch.
        model_config(dict): the dictionary containing model configuration.
    
    Raises:
        NameError: if key ``task`` in ``model_config`` is invalid.

    Returns:
        reader(func): data reader.
    """
    task = model_config['task']

    if task == 'pretrain':
        return pretrain_sample_reader(filenames, batch_size)
    elif task == 'seq_classification':
        label_name = model_config.get('label_name', 'labels')
        return sequence_sample_reader(filenames, batch_size, label_name)
    elif task in ['classification', 'regression']:
        label_name = model_config.get('label_name', 'labels')
        return normal_sample_reader(filenames, batch_size, label_name)
    else:
        raise NameError('Task %s is unsupport.' % task)


def setup_data_loader(input_list, model_config, data_path, trainer_id, trainer_num, places, batch_size):
    """Setup the data_loader.

    Args:
        input_list(list): the feed_list of the model.
        model_config(dict): the dictionary containing model configuration.
        data_path(str): the directory containing data files.
        trainer_id(int): the id of current trainer.
        trainer_num(int): the number of trainers.
        places: the place to store the loaded data.
        batch_size(int) batch size.
    
    Raises:
        NameError: if key ``task`` in ``model_config`` is invalid.

    Returns:
        data_loader(fluid.io.DataLoader): data reader.
    """
    data_loader = fluid.io.DataLoader.from_generator(
            feed_list=input_list,
            capacity=256,
            use_double_buffer=True,
            iterable=True)

    filenames = get_part_files(data_path, trainer_id, trainer_num)
    data_loader.set_sample_list_generator(
            get_sample_generator(filenames, batch_size, model_config),
            places=places)
    return data_loader


def gen_batch_data(examples, tokenizer, place):
    """Generate batch for prediction.

    Args:
        examples(list): the list of examples containing amino acid sequences.
        tokenizer(pahelix.utils.ProteinTools.ProteinTokenizer): tokenizer to generate the token ids.
        place: the place to store the loaded data.

    Returns:
        batch_data: the orgainized data.
    """
    token_ids = []
    pos = []
    lods = [0]
    for example in examples:
        cur_token_ids = tokenizer.gen_token_ids(example)
        token_ids.extend(cur_token_ids)
        pos.extend(np.arange(len(cur_token_ids)).tolist())
        lods.append(len(token_ids))
    token_tensor = fluid.core.LoDTensor()
    token_tensor.set(np.array(token_ids, dtype='int64').reshape([-1, 1]), place)
    token_tensor.set_lod([lods])
    pos_tensor = fluid.core.LoDTensor()
    pos_tensor.set(np.array(pos, dtype='int64').reshape([-1, 1]), place)
    pos_tensor.set_lod([lods])

    return {'protein_token': token_tensor, 'protein_pos': pos_tensor}
