# <p style="text-align: center;">Synthbuster: Towards Detection of Diffusion Model Generated Images</p>

## <p style="text-align: center;">Quentin Bammey</p>

### <p style="text-align: center;">Université Paris-Saclay, ENS Paris-Saclay, CNRS, Centre Borelli</p>

## Database of synthetic images

This dataset contains synthetic, AI-generated images from 9 different models:

* DALL·E 2
* DALL·E 3
* Adobe Firefly
* Midjourney v5
* Stable Diffusion 1.3
* Stable Diffusion 1.4
* Stable Diffusion 2
* Stable Diffusion XL
* Glide

1000 images were generated per model. The images are loosely based on raise-1k images (Dang-Nguyen, Duc-Tien, et al. "Raise: A raw images dataset for digital image forensics." Proceedings of the 6th ACM multimedia systems conference. 2015.). For each image of the raise-1k dataset, a description was generated using the Midjourney /describe function and CLIP interrogator (https://github.com/pharmapsychotic/clip-interrogator/). Each of these prompts was manually edited to produce results as photorealistic as possible and remove living persons and artists names.

In addition to this, parameters were randomly selected within reasonable values for methods requiring so.
The prompts and parameters used for each method can be found in the `prompts.csv` file.

This dataset can be used to evaluate AI-generated image detection methods. We recommend matching the generated images with the real Raise-1k images, to evaluate whether the methods can distinguish the two of them. Raise-1k images are not included in the dataset, they can be downloaded separately at (http://loki.disi.unitn.it/RAISE/download.html).

None of the images suffered degradations such as JPEG compression or resampling, which leaves room to add your own degradations to test robustness to various transformation in a controlled manner.
