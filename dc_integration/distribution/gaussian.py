from dataclasses import dataclass, field
import numpy as np
from sklearn.mixture.gaussian_mixture import _compute_precision_cholesky
from sklearn.mixture.gaussian_mixture import _compute_log_det_cholesky
from dc_integration.utils import is_broadcast_compatible
from dc_integration.distribution.utils import _ProbabilisticModel


@dataclass
class Gaussian(_ProbabilisticModel):
    mean: np.array  # (..., D)
    covariance: np.array  # (..., D, D)
    precision_cholesky: np.array = field(init=False)  # (..., D, D)
    log_det_precision_cholesky: np.array = field(init=False)  # (...,)

    def __post_init__(self):
        D = self.mean.shape[-1]
        c = np.reshape(self.covariance, (-1, D, D))
        pc = _compute_precision_cholesky(c, 'full')
        self.precision_cholesky = np.reshape(pc, self.covariance.shape)
        self.log_det_precision_cholesky = _compute_log_det_cholesky(pc, 'full', D)

    def log_pdf(self, x):
        """Gets used by e.g. the GMM.

        Args:
            x: Shape (..., N, D)

        Returns:

        """
        D = self.mean.shape[-1]
        difference = x - self.mean[..., None, :]
        white_x = np.einsum(
            '...dD,...nD->...nd',
            self.precision_cholesky,
            difference
        )
        return (
                - 1 / 2 * D * np.log(2 * np.pi)
                + self.log_det_precision_cholesky[..., None]
                - 1 / 2 * np.einsum('...nd,...nd->...n', white_x, white_x)
        )


@dataclass
class DiagonalGaussian(_ProbabilisticModel):
    mean: np.array  # (..., D)
    covariance: np.array  # (..., D)
    precision_cholesky: np.array = field(init=False)  # (..., D)
    log_det_precision_cholesky: np.array = field(init=False)  # (...,)

    def __post_init__(self):
        D = self.mean.shape[-1]
        c = np.reshape(self.covariance, (-1, D))
        pc = _compute_precision_cholesky(c, 'diag')
        self.precision_cholesky = np.reshape(pc, self.covariance.shape)
        self.log_det_precision_cholesky = _compute_log_det_cholesky(pc, 'diag', D)

    def log_pdf(self, x):
        """Gets used by e.g. the GMM.

        Args:
            x: Shape (..., N, D)

        Returns:

        """
        D = self.mean.shape[-1]
        difference = x - self.mean[..., None, :]
        white_x = np.einsum(
            '...dD,...nD->...nd',
            self.precision_cholesky,
            difference
        )
        return (
                - 1 / 2 * D * np.log(2 * np.pi)
                + self.log_det_precision_cholesky[..., None]
                - 1 / 2 * np.einsum('...nd,...nd->...n', white_x, white_x)
        )


@dataclass
class SphericalGaussian(_ProbabilisticModel):
    mean: np.array  # (..., D)
    covariance: np.array  # (...,)
    precision_cholesky: np.array = field(init=False)  # (...,)
    log_det_precision_cholesky: np.array = field(init=False)  # (...,)

    def __post_init__(self):
        D = self.mean.shape[-1]
        c = np.reshape(self.covariance, (-1,))
        pc = _compute_precision_cholesky(c, 'diag')
        self.precision_cholesky = np.reshape(pc, self.covariance.shape)
        self.log_det_precision_cholesky = _compute_log_det_cholesky(pc, 'spherical', D)

    def log_pdf(self, x):
        """Gets used by e.g. the GMM.

        Args:
            x: Shape (..., N, D)

        Returns:

        """
        D = self.mean.shape[-1]
        difference = x - self.mean[..., None, :]
        white_x = np.einsum(
            '...,...nd->...nd',
            self.precision_cholesky,
            difference
        )
        return (
                - 1 / 2 * D * np.log(2 * np.pi)
                + self.log_det_precision_cholesky[..., None]
                - 1 / 2 * np.einsum('...nd,...nd->...n', white_x, white_x)
        )


class GaussianTrainer:
    def fit(self, x, saliency=None, covariance_type="full"):
        """

        Args:
            x: Shape (..., N, D)
            saliency: Importance weighting for each observation, shape (..., N)
            covariance_type: Either 'full', 'diagonal', or 'spherical'

        Returns:

        """
        assert np.isrealobj(x), x.dtype
        if saliency is not None:
            assert is_broadcast_compatible(x.shape[:-1], saliency.shape), (
                x.shape, saliency.shape
            )
        return self._fit(x, saliency=saliency, covariance_type=covariance_type)

    def _fit(self, x, saliency, covariance_type):
        dimension = x.shape[-1]

        if saliency is None:
            denominator = np.array(x.shape[-2])
            mean = np.einsum("...nd->...d", x)
        else:
            denominator = np.maximum(
                np.einsum("...n->...", saliency),
                np.finfo(x.dtype).tiny
            )
            mean = np.einsum("...n,...nd->...d", saliency, x)
        mean /= denominator[..., None]

        difference = x - mean[..., None, :]

        if covariance_type == "full":
            operation = "...nd,...nD->...dD"
            denominator = denominator[..., None, None]
            model_cls = Gaussian
        elif covariance_type == "diagonal":
            operation = "...nd,...nd->...d"
            denominator = denominator[..., None]
            model_cls = DiagonalGaussian
        elif covariance_type == "spherical":
            operation = "...nd,...nd->..."
            model_cls = SphericalGaussian
            denominator = denominator * dimension
        else:
            raise ValueError(f"Unknown covariance type '{covariance_type}'.")

        if saliency is None:
            covariance = np.einsum(operation, difference, difference)
        else:
            operation = "...n," + operation
            covariance = np.einsum(operation, saliency, difference, difference)
        covariance /= denominator
        return model_cls(mean=mean, covariance=covariance)
