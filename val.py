'''
Copyright (C) 2010-2021 Alibaba Group Holding Limited.
'''

'''
Usage:
python val.py --gpu 0 --arch zennet_imagenet1k_latency02ms_res192
'''
import os, sys, argparse, math, PIL
import torch
from torchvision import transforms, datasets
import ZiCo

imagenet_data_dir = os.path.expanduser('~/dataset/imagenet')

def accuracy(output, target, topk=(1, )):
    """Computes the accuracy over the k top predictions for the specified values of k"""
    with torch.no_grad():
        maxk = max(topk)
        batch_size = target.size(0)
        print(output.size(), target.size())
        _, pred = output.topk(maxk, 1, True, True)
        pred = pred.t()
        correct = pred.eq(target.view(1, -1).expand_as(pred))

        res = []
        for k in topk:
            correct_k = correct[:k].reshape(-1).float().sum(0, keepdim=True)
            res.append(correct_k.mul_(100.0 / batch_size))
        return res


if __name__ == '__main__':
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--batch_size', type=int, default=128,
                        help='batch size for evaluation.')
    parser.add_argument('--workers', type=int, default=6,
                        help='number of workers to load dataset.')
    parser.add_argument('--gpu', type=int, default=None,
                        help='GPU device ID. None for CPU.')
    parser.add_argument('--data', type=str, default=imagenet_data_dir,
                        help='ImageNet data directory.')
    parser.add_argument('--arch', type=str, default=None,
                        help='model to be evaluated.')
    parser.add_argument('--fp16', action='store_true')
    parser.add_argument('--apex', action='store_true',
                        help='Use NVIDIA Apex (float16 precision).')
    parser.add_argument('--ckpt_path', type=str, default=None,
                        help='the path of checkpoint')

    opt, _ = parser.parse_known_args(sys.argv)

    if opt.apex:
        from apex import amp
    # else:
    #     print('Warning!!! The GENets are trained by NVIDIA Apex, '
    #           'it is suggested to turn on --apex in the evaluation. '
    #           'Otherwise the model accuracy might be harmed.')

    input_image_size = ZiCo.ZiCo_model_zoo[opt.arch]['resolution']
    crop_image_size = ZiCo.ZiCo_model_zoo[opt.arch]['crop_image_size']

    print('Evaluate {} at {}x{} resolution.'.format(opt.arch, input_image_size, input_image_size))

    # load dataset
    val_dir = os.path.join(opt.data, 'val')
    input_image_crop = 0.875
    resize_image_size = int(math.ceil(crop_image_size / input_image_crop))
    transforms_normalize = transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
    transform_list = [transforms.Resize(resize_image_size, interpolation=PIL.Image.BICUBIC),
                      transforms.CenterCrop(crop_image_size), transforms.ToTensor(), transforms_normalize]
    transformer = transforms.Compose(transform_list)
    val_dataset = datasets.ImageFolder(val_dir, transformer)
    val_loader = torch.utils.data.DataLoader(val_dataset, batch_size=opt.batch_size, shuffle=False,
                                              num_workers=opt.workers, pin_memory=True, sampler=None)
    
    # load model
    model = ZiCo.get_ZiCo(opt.arch, pretrained=True, ckptpath=opt.ckpt_path)
    if opt.gpu is not None:
        torch.cuda.set_device(opt.gpu)
        torch.backends.cudnn.benchmark = True
        model = model.cuda(opt.gpu)
        print('Using GPU {}.'.format(opt.gpu))
        if opt.apex:
            model = amp.initialize(model, opt_level="O1")
        elif opt.fp16:
            model = model.half()

    model.eval()
    acc1_sum = 0
    acc5_sum = 0
    n = 0
    with torch.no_grad():
        for i, (input, target) in enumerate(val_loader):

            if opt.gpu is not None:
                input = input.cuda(opt.gpu, non_blocking=True)
                target = target.cuda(opt.gpu, non_blocking=True)
                if opt.fp16:
                    input = input.half()

            input = torch.nn.functional.interpolate(input, input_image_size, mode='bilinear')

            output = model(input)
            acc1, acc5 = accuracy(output, target, topk=(1, 5))

            acc1_sum += acc1[0] * input.shape[0]
            acc5_sum += acc5[0] * input.shape[0]
            n += input.shape[0]

            if i % 100 == 0:
                print('mini_batch {}, top-1 acc={:4g}%, top-5 acc={:4g}%, number of evaluated images={}'.format(i, acc1[0], acc5[0], n))
            pass
        pass
    pass

    acc1_avg = acc1_sum / n
    acc5_avg = acc5_sum / n

    print('*** arch={}, validation top-1 acc={:.2f}%, top-5 acc={:.2f}%, number of evaluated images={}'.format(opt.arch, acc1_avg, acc5_avg, n))