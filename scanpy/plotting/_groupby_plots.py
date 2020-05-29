"""Plotting functions for AnnData.
"""
import collections.abc as cabc
from typing import Optional, Union, Mapping  # Special
from typing import Sequence, Iterable  # ABCs
from typing import Tuple  # Classes

import numpy as np
import pandas as pd
from anndata import AnnData
from matplotlib.axes import Axes
from matplotlib import pyplot as pl
from matplotlib import gridspec, rcParams
from matplotlib.colors import is_color_like

from .. import logging as logg
from .._utils import _doc_params
from .._compat import Literal
from . import _utils
from ._utils import make_grid_spec, fix_kwds
from ._utils import ColorLike, _AxesSubplot
from ._docs import doc_common_plot_args, doc_show_save_ax
from ._anndata import _plot_dendrogram, _get_dendrogram_key, _prepare_dataframe

_VarNames = Union[str, Sequence[str]]


class BasePlot(object):
    """\
    Generic class for the visualization of AnnData categories and
    selected `var` (features or genes).

    Takes care of the visual location of a main plot, additional plots
    in the margins (e.g. dendrogram, margin totals) and legends. Also
    understand how to adapt the visual parameter if the plot is rotated

    """

    DEFAULT_SAVE_PREFIX = 'baseplot_'
    MIN_FIGURE_HEIGHT = 2.5
    DEFAULT_CATEGORY_HEIGHT = 0.35
    DEFAULT_CATEGORY_WIDTH = 0.37

    DEFAULT_COLORMAP = 'winter'
    DEFAULT_LEGENDS_WIDTH = 1.5
    DEFAULT_COLOR_LEGEND_TITLE = 'Expression\nlevel in group'

    def __init__(
        self,
        adata: AnnData,
        var_names: Union[_VarNames, Mapping[str, _VarNames]],
        groupby: str,
        use_raw: Optional[bool] = None,
        log: bool = False,
        num_categories: int = 7,
        categories_order: Optional[Sequence[str]] = None,
        title: Optional['str'] = None,
        figsize: Optional[Tuple[float, float]] = None,
        gene_symbols: Optional[str] = None,
        var_group_positions: Optional[Sequence[Tuple[int, int]]] = None,
        var_group_labels: Optional[Sequence[str]] = None,
        var_group_rotation: Optional[float] = None,
        layer: Optional[str] = None,
        ax: Optional[_AxesSubplot] = None,
        **kwds,
    ):
        self.var_names = var_names
        self.var_group_labels = var_group_labels
        self.var_group_positions = var_group_positions
        self.var_group_rotation = var_group_rotation
        self.width, self.height = figsize if figsize is not None else (None, None)

        if use_raw is None and adata.raw is not None:
            use_raw = True

        self.has_var_groups = (
            True
            if var_group_positions is not None and len(var_group_positions) > 0
            else False
        )

        self._update_var_groups()

        self.categories, self.obs_tidy = _prepare_dataframe(
            adata,
            self.var_names,
            groupby,
            use_raw,
            log,
            num_categories,
            layer=layer,
            gene_symbols=gene_symbols,
        )

        if categories_order is not None:
            if set(self.obs_tidy.index.categories) != set(categories_order):
                logg.error(
                    "Please check that the categories given by "
                    "the `order` parameter match the categories that "
                    "want to be reordered.\n\n"
                    "Mismatch: "
                    f"{set(obs_tidy.index.categories).difference(categories_order)}\n\n"
                    f"Given order categories: {categories_order}\n\n"
                    f"{groupby} categories: {list(obs_tidy.index.categories)}\n"
                )
                return

        self.adata = adata
        self.groupby = groupby
        self.log = log
        self.kwds = kwds

        # set default values for legend
        self.color_legend_title = self.DEFAULT_COLOR_LEGEND_TITLE
        self.legends_width = self.DEFAULT_LEGENDS_WIDTH

        # set style defaults
        self.cmap = self.DEFAULT_COLORMAP

        # style default parameters
        self.are_axes_swapped = False
        self.categories_order = categories_order
        self.var_names_idx_order = None

        # minimum height required for legends to plot properly
        self.min_figure_height = self.MIN_FIGURE_HEIGHT

        self.fig_title = title

        self.group_extra_size = 0
        self.plot_group_extra = None
        # after show() is called ax_dict contains a dictionary of the axes used in
        # the plot
        self.ax_dict = None
        self.ax = ax

    def swap_axes(self, swap_axes: Optional[bool] = True):
        """
        Plots a transposed image.

        By default, the x axis contains `var_names` (e.g. genes) and the y
        axis the `groupby` categories. By setting `swap_axes` then x are
        the `groupby` categories and y the `var_names`.

        Parameters
        ----------
        swap_axes : bool, default: True

        Returns
        -------
        BasePlot

        """
        self.DEFAULT_CATEGORY_HEIGHT, self.DEFAULT_CATEGORY_WIDTH = (
            self.DEFAULT_CATEGORY_WIDTH,
            self.DEFAULT_CATEGORY_HEIGHT,
        )

        self.are_axes_swapped = swap_axes
        return self

    def add_dendrogram(
        self,
        show: Optional[bool] = True,
        dendrogram_key: Optional[str] = None,
        size: Optional[float] = 0.8,
    ):
        """
        Show dendrogram based on the hierarchical clustering between the `groupby`
        categories. Categories are reordered to match the dendrogram order.

        The dendrogram information is computed using :func:`scanpy.tl.dendrogram`.
        If `sc.tl.dendrogram` has not been called previously the function is called
        with default parameters.

        The dendrogram is by default shown on the right side of the plot or on top
        if the axes are swapped.

        `var_names` are reordered to produce a more pleasing output if:
            * The data contains `var_groups`
            * the `var_groups` match the categories.
        The previous conditions happen by default when using Plot
        to show the results from `sc.tl.rank_genes_groups` (aka gene markers), by
        calling `sc.tl.rank_genes_groups_(plot_name)`.

        Parameters
        ----------
        show : bool, default True
        dendrogram_key : str, default None
            Needed if `sc.tl.dendrogram` saved the dendrogram using a key different
            than the default name.
        size : size of the dendrogram. Corresponds to width when dendrogram shown on
            the right of the plot, or height when shown on top.

        Returns
        -------
        BasePlot

        Examples
        --------
        >>> adata = sc.datasets.pbmc68k_reduced()
        >>> markers = {{'T-cell': 'CD3D', 'B-cell': 'CD79A', 'myeloid': 'CST3'}}
        >>> sc.pl.BasePlot(adata, markers, groupby='bulk_labels').add_dendrogram().show()

        """

        if not show:
            self.plot_group_extra = None
            return self

        if self.groupby is None or len(self.categories) <= 2:
            # dendrogram can only be computed  between groupby categories
            logg.warning(
                "Dendrogram not added. Dendrogram is added only "
                "when the number of categories to plot > 2"
            )
            return self

        self.group_extra_size = size

        # to correctly plot the dendrogram the categories need to be ordered
        # according to the dendrogram ordering.
        self._reorder_categories_after_dendrogram(dendrogram_key)

        dendro_ticks = np.arange(len(self.categories)) + 0.5

        self.group_extra_size = size
        self.plot_group_extra = {
            'kind': 'dendrogram',
            'width': size,
            'dendrogram_key': dendrogram_key,
            'dendrogram_ticks': dendro_ticks,
        }
        return self

    def add_totals(
        self,
        show: Optional[bool] = True,
        sort: Literal['ascending', 'descending'] = None,
        size: Optional[float] = 0.8,
        color: Optional[Union[ColorLike, Sequence[ColorLike]]] = None,
    ):
        """
        Show barplot for the number of cells in in `groupby` category.

        The barplot is by default shown on the right side of the plot or on top
        if the axes are swapped.

        Parameters
        ----------
        show : bool, default True
        sort : Set to either 'ascending' or 'descending' to reorder the categories
            by cell number
        size : size of the barplot. Corresponds to width when shown on
            the right of the plot, or height when shown on top.
        color: Color for the bar plots or list of colors for each of the bar plots.
            By default, each bar plot uses the colors assigned in `adata.uns[{groupby}_colors.
        Returns
        -------
        BasePlot

        Examples
        --------
        >>> adata = sc.datasets.pbmc68k_reduced()
        >>> markers = {{'T-cell': 'CD3D', 'B-cell': 'CD79A', 'myeloid': 'CST3'}}
        >>> sc.pl.BasePlot(adata, markers, groupby='bulk_labels').add_totals().show()
        """
        self.group_extra_size = size

        if not show:
            # hide totals
            self.plot_group_extra = None
            self.group_extra_size = 0
            return self

        _sort = True if sort is not None else False
        _ascending = True if sort == 'ascending' else False
        counts_df = self.adata.obs[self.groupby].value_counts(
            sort=_sort, ascending=_ascending
        )

        if _sort:
            self.categories_order = counts_df.index

        self.plot_group_extra = {
            'kind': 'group_totals',
            'width': size,
            'sort': sort,
            'counts_df': counts_df,
            'color': color,
        }
        return self

    def style(self, cmap: Optional[str] = DEFAULT_COLORMAP):
        self.cmap = cmap

    def legend(
        self,
        show: Optional[bool] = True,
        title: Optional[str] = DEFAULT_COLOR_LEGEND_TITLE,
        width: Optional[float] = DEFAULT_LEGENDS_WIDTH,
    ):
        """
        Configure legend parameters.

        Parameters
        ----------
        show
            Set to `False` to hide the default plot of the legend.
        title
            Title for the dot size legend. Use "\n" to add line breaks.
        width
            Width of the legend.

        Returns
        -------
        BasePlot

        Examples
        --------
        >>> adata = sc.datasets.pbmc68k_reduced()
        >>> markers = {{'T-cell': 'CD3D', 'B-cell': 'CD79A', 'myeloid': 'CST3'}}
        >>> dp = sc.pl.BasePlot(adata, markers, groupby='bulk_labels')
        >>> dp.legend(colorbar_title='log(UMI counts + 1)').show()
        """

        if not show:
            # turn of legends by setting width to 0
            self.legends_width = 0
        else:
            self.color_legend_title = title
            self.legends_width = width

        return self

    def get_axes(self):
        return self.ax_dict

    def _plot_totals(
        self, total_barplot_ax: Axes, orientation: Literal['top', 'right']
    ):
        """
        Makes the bar plot for totals
        """
        params = self.plot_group_extra
        counts_df = params['counts_df']
        if self.categories_order is not None:
            counts_df = counts_df.loc[self.categories_order]
        if params['color'] is None:
            if f'{self.groupby}_colors' in self.adata.uns:
                color = self.adata.uns[f'{self.groupby}_colors']
            else:
                color = 'salmon'
        else:
            color = params['color']

        if orientation == 'top':
            counts_df.plot(
                kind="bar",
                color=color,
                position=0.5,
                ax=total_barplot_ax,
                edgecolor="black",
                width=0.65,
            )
            # add numbers to the top of the bars
            max_y = max([p.get_height() for p in total_barplot_ax.patches])

            for p in total_barplot_ax.patches:
                p.set_x(p.get_x() + 0.5)
                if p.get_height() >= 1000:
                    display_number = f'{np.round(p.get_height()/1000, decimals=1)}k'
                else:
                    display_number = np.round(p.get_height(), decimals=1)
                total_barplot_ax.annotate(
                    display_number,
                    (p.get_x() + p.get_width() / 2.0, (p.get_height() + max_y * 0.05)),
                    ha="center",
                    va="top",
                    xytext=(0, 10),
                    fontsize="x-small",
                    textcoords="offset points",
                )
            # for k in total_barplot_ax.spines.keys():
            #     total_barplot_ax.spines[k].set_visible(False)
            total_barplot_ax.set_ylim(0, max_y * 1.4)

        elif orientation == 'right':
            counts_df.plot(
                kind="barh",
                color=color,
                position=-0.3,
                ax=total_barplot_ax,
                edgecolor="black",
                width=0.65,
            )

            # add numbers to the right of the bars
            max_x = max([p.get_width() for p in total_barplot_ax.patches])
            for p in total_barplot_ax.patches:
                if p.get_width() >= 1000:
                    display_number = f'{np.round(p.get_width()/1000, decimals=1)}k'
                else:
                    display_number = np.round(p.get_width(), decimals=1)
                total_barplot_ax.annotate(
                    display_number,
                    ((p.get_width()), p.get_y() + p.get_height()),
                    ha="center",
                    va="top",
                    xytext=(10, 10),
                    fontsize="x-small",
                    textcoords="offset points",
                )
            total_barplot_ax.set_xlim(0, max_x * 1.4)

        total_barplot_ax.grid(False)
        total_barplot_ax.axis("off")

    def _plot_colorbar(self, color_legend_ax: Axes, normalize):
        """
        Plots a horizontal colorbar given the ax an normalize values

        Parameters
        ----------
        color_legend_ax
        normalize

        Returns
        -------
        None, updates color_legend_ax

        """
        cmap = pl.get_cmap(self.cmap)
        import matplotlib.colorbar

        matplotlib.colorbar.ColorbarBase(
            color_legend_ax, orientation='horizontal', cmap=cmap, norm=normalize
        )

        color_legend_ax.set_title(self.color_legend_title, fontsize='small')

        color_legend_ax.xaxis.set_tick_params(labelsize='small')

    def _plot_legend(self, legend_ax, return_ax_dict, normalize):

        # to maintain the fixed height size of the legends, a
        # spacer of variable height is added at top and bottom.
        # The structure for the legends is:
        # first row: variable space to keep the first rows of the same size
        # second row: size legend

        legend_height = self.min_figure_height * 0.08
        height_ratios = [
            self.height - legend_height,
            legend_height,
        ]
        fig, legend_gs = make_grid_spec(
            legend_ax, nrows=2, ncols=1, height_ratios=height_ratios,
        )

        color_legend_ax = fig.add_subplot(legend_gs[1])

        self._plot_colorbar(color_legend_ax, normalize)
        return_ax_dict['color_legend_ax'] = color_legend_ax

    def _mainplot(self, ax):
        import matplotlib.colors

        y_labels = self.categories
        x_labels = self.var_names

        if self.var_names_idx_order is not None:
            x_labels = [x_labels[x] for x in self.var_names_idx_order]

        if self.categories_order is not None:
            y_labels = self.categories_order

        if self.are_axes_swapped:
            x_labels, y_labels = y_labels, x_labels
            ax.set_xlabel(self.groupby)
        else:
            ax.set_ylabel(self.groupby)

        y_ticks = np.arange(len(y_labels)) + 0.5
        ax.set_yticks(y_ticks)
        ax.set_yticklabels(y_labels)

        x_ticks = np.arange(len(x_labels)) + 0.5
        ax.set_xticks(x_ticks)
        ax.set_xticklabels(x_labels, rotation=90, ha='center', minor=False)

        ax.tick_params(axis='both', labelsize='small')
        ax.grid(False)

        # to be consistent with the heatmap plot, is better to
        # invert the order of the y-axis, such that the first group is on
        # top
        ax.set_ylim(len(y_labels), 0)
        ax.set_xlim(0, len(x_labels))

        normalize = matplotlib.colors.Normalize(
            vmin=self.kwds.get('vmin'), vmax=self.kwds.get('vmax')
        )

        return normalize

    def show(
        self, show: Optional[bool] = None, save: Union[str, bool, None] = None,
    ):
        """
        Render the image

        Parameters
        ----------
        show
             Show the plot, do not return axis. If false, plot is not shown
             and axes returned.
        save
            If `True` or a `str`, save the figure.
            A string is appended to the default filename.
            Infer the filetype if ending on {{`'.pdf'`, `'.png'`, `'.svg'`}}.

        Returns
        -------
        If `show=False`: Dict of :class:`~matplotlib.axes.Axes`. The dict key indicates the
        type of ax (eg. mainplot_ax)

        Examples
        -------
        >>> adata = sc.datasets.pbmc68k_reduced()
        >>> markers = ['C1QA', 'PSAP', 'CD79A', 'CD79B', 'CST3', 'LYZ']
        >>> sc.pl.Plot(adata, markers, groupby='bulk_labels').show()

        Get the axes
        >>> axes_dict = sc.pl.Plot(adata, markers, groupby='bulk_labels').show(show=False)
        >>> axes_dict['mainplot_ax'].grid(True)
        >>> plt.show()

        Save image
        >>> sc.pl.BasePlot(adata, markers, groupby='bulk_labels').show(save='plot.pdf')

        """
        category_height = self.DEFAULT_CATEGORY_HEIGHT
        category_width = self.DEFAULT_CATEGORY_WIDTH

        if self.height is None:
            mainplot_height = len(self.categories) * category_height
            mainplot_width = (
                len(self.var_names) * category_width + self.group_extra_size
            )
            if self.are_axes_swapped:
                mainplot_height, mainplot_width = mainplot_width, mainplot_height

            height = mainplot_height + 1  # +1 for labels

            # if the number of categories is small use
            # a larger height, otherwise the legends do not fit
            self.height = max([self.min_figure_height, height])
            self.width = mainplot_width + self.legends_width
        else:
            self.min_figure_height = self.height
            mainplot_height = self.height

            mainplot_width = self.width - (self.legends_width + self.group_extra_size)

        return_ax_dict = {}
        # define a layout of 1 rows x 2 columns
        #   first ax is for the main figure.
        #   second ax is to plot legends
        legends_width_spacer = 0.7 / self.width

        fig, gs = make_grid_spec(
            self.ax or (self.width, self.height),
            nrows=1,
            ncols=2,
            wspace=legends_width_spacer,
            width_ratios=[mainplot_width + self.group_extra_size, self.legends_width],
        )

        # the main plot is divided into three rows and two columns
        # first row is an spacer, that is adjusted in case the
        #           legends need more height than the main plot
        # second row is for brackets (if needed),
        # third row is for mainplot and dendrogram (if needed)
        if self.has_var_groups:
            # add some space in case 'brackets' want to be plotted on top of the image
            if self.are_axes_swapped:
                var_groups_height = category_height
            else:
                var_groups_height = category_height / 2

        else:
            var_groups_height = 0

        mainplot_width = mainplot_width - self.group_extra_size
        spacer_height = self.height - var_groups_height - mainplot_height
        if not self.are_axes_swapped:
            height_ratios = [spacer_height, var_groups_height, mainplot_height]
            width_ratios = [mainplot_width, self.group_extra_size]

        else:
            height_ratios = [spacer_height, self.group_extra_size, mainplot_height]
            width_ratios = [mainplot_width, var_groups_height]
            # gridspec is the same but rows and columns are swapped

        if self.fig_title is not None and self.fig_title.strip() != '':
            # for the figure title use the ax that contains
            # all the main graphical elements (main plot, dendrogram etc)
            # otherwise the title may overlay with the figure.
            # also, this puts the title centered on the main figure and not
            # centered between the main figure and the legends
            _ax = fig.add_subplot(gs[0, 0])
            _ax.axis('off')
            _ax.set_title(self.fig_title)

        mainplot_gs = gridspec.GridSpecFromSubplotSpec(
            nrows=3,
            ncols=2,
            wspace=0.0,
            hspace=0.0,
            subplot_spec=gs[0, 0],
            width_ratios=width_ratios,
            height_ratios=height_ratios,
        )
        main_ax = fig.add_subplot(mainplot_gs[2, 0])
        return_ax_dict['mainplot_ax'] = main_ax

        if not self.are_axes_swapped:
            if self.plot_group_extra is not None:
                group_extra_ax = fig.add_subplot(mainplot_gs[2, 1], sharey=main_ax)
                group_extra_orientation = 'right'
            if self.has_var_groups:
                gene_groups_ax = fig.add_subplot(mainplot_gs[1, 0], sharex=main_ax)
                var_group_orientation = 'top'
        else:
            if self.plot_group_extra:
                group_extra_ax = fig.add_subplot(mainplot_gs[1, 0], sharex=main_ax)
                group_extra_orientation = 'top'
            if self.has_var_groups:
                gene_groups_ax = fig.add_subplot(mainplot_gs[2, 1], sharey=main_ax)
                var_group_orientation = 'right'

        if self.plot_group_extra is not None:
            if self.plot_group_extra['kind'] == 'dendrogram':
                _plot_dendrogram(
                    group_extra_ax,
                    self.adata,
                    self.groupby,
                    dendrogram_key=self.plot_group_extra['dendrogram_key'],
                    ticks=self.plot_group_extra['dendrogram_ticks'],
                    orientation=group_extra_orientation,
                )
            if self.plot_group_extra['kind'] == 'group_totals':
                self._plot_totals(group_extra_ax, group_extra_orientation)

            return_ax_dict['group_extra_ax'] = group_extra_ax

        # plot group legends on top or left of main_ax (if given)
        if self.has_var_groups:
            self._plot_var_groups_brackets(
                gene_groups_ax,
                group_positions=self.var_group_positions,
                group_labels=self.var_group_labels,
                rotation=self.var_group_rotation,
                left_adjustment=0.2,
                right_adjustment=0.7,
                orientation=var_group_orientation,
            )
            return_ax_dict['gene_group_ax'] = gene_groups_ax

        # plot the mainplot
        normalize = self._mainplot(main_ax)

        # code from pandas.plot in add_totals adds
        # minor ticks that need to be removed
        main_ax.yaxis.set_tick_params(which='minor', left=False, right=False)
        main_ax.xaxis.set_tick_params(which='minor', top=False, bottom=False, length=0)
        main_ax.set_zorder(100)
        if self.legends_width > 0:
            legend_ax = fig.add_subplot(gs[0, 1])
            self._plot_legend(legend_ax, return_ax_dict, normalize)

        _utils.savefig_or_show(self.DEFAULT_SAVE_PREFIX, show=show, save=save)
        self.ax_dict = return_ax_dict

        if show is False:
            return return_ax_dict

    def _reorder_categories_after_dendrogram(
        self, dendrogram,
    ):
        """\
        Function used by plotting functions that need to reorder the the groupby
        observations based on the dendrogram results.

        The function checks if a dendrogram has already been precomputed.
        If not, `sc.tl.dendrogram` is run with default parameters.

        The results found in `.uns[dendrogram_key]` are used to reorder
        `var_group_labels` and `var_group_positions`.


        Returns
        -------
        None internally updates
        'categories_idx_ordered', 'var_group_names_idx_ordered',
        'var_group_labels' and 'var_group_positions'
        """

        def _format_first_three_categories(_categories):
            """used to clean up warning message"""
            _categories = list(_categories)
            if len(_categories) > 3:
                _categories = _categories[:3] + ['etc.']
            return ', '.join(_categories)

        key = _get_dendrogram_key(self.adata, dendrogram, self.groupby)

        dendro_info = self.adata.uns[key]
        if self.groupby != dendro_info['groupby']:
            raise ValueError(
                "Incompatible observations. The precomputed dendrogram contains "
                f"information for the observation: '{self.groupby}' while the plot is "
                f"made for the observation: '{dendro_info['groupby']}. "
                "Please run `sc.tl.dendrogram` using the right observation.'"
            )

        # order of groupby categories
        categories_idx_ordered = dendro_info['categories_idx_ordered']
        categories_ordered = dendro_info['categories_ordered']

        if len(self.categories) != len(categories_idx_ordered):
            raise ValueError(
                "Incompatible observations. Dendrogram data has "
                f"{len(categories_idx_ordered)} categories but current groupby "
                f"observation {self.groupby!r} contains {len(self.categories)} categories. "
                "Most likely the underlying groupby observation changed after the "
                "initial computation of `sc.tl.dendrogram`. "
                "Please run `sc.tl.dendrogram` again.'"
            )

        # reorder var_groups (if any)
        if self.var_names is not None:
            var_names_idx_ordered = list(range(len(self.var_names)))

        if self.has_var_groups:
            if set(self.var_group_labels) == set(self.categories):
                positions_ordered = []
                labels_ordered = []
                position_start = 0
                var_names_idx_ordered = []
                for cat_name in categories_ordered:
                    idx = self.var_group_labels.index(cat_name)
                    position = self.var_group_positions[idx]
                    _var_names = self.var_names[position[0] : position[1] + 1]
                    var_names_idx_ordered.extend(range(position[0], position[1] + 1))
                    positions_ordered.append(
                        (position_start, position_start + len(_var_names) - 1)
                    )
                    position_start += len(_var_names)
                    labels_ordered.append(self.var_group_labels[idx])
                self.var_group_labels = labels_ordered
                self.var_group_positions = positions_ordered
            else:
                logg.warning(
                    "Groups are not reordered because the `groupby` categories "
                    "and the `var_group_labels` are different.\n"
                    f"categories: {_format_first_three_categories(self.categories)}\n"
                    "var_group_labels: "
                    f"{_format_first_three_categories(self.var_group_labels)}"
                )

        if var_names_idx_ordered is not None:
            var_names_ordered = [self.var_names[x] for x in var_names_idx_ordered]
        else:
            var_names_ordered = None

        self.categories_idx_ordered = categories_idx_ordered
        self.categories_order = dendro_info['categories_ordered']
        self.var_names_idx_order = var_names_idx_ordered
        self.var_names_ordered = var_names_ordered

    @staticmethod
    def _plot_var_groups_brackets(
        gene_groups_ax: Axes,
        group_positions: Iterable[Tuple[int, int]],
        group_labels: Sequence[str],
        left_adjustment: float = -0.3,
        right_adjustment: float = 0.3,
        rotation: Optional[float] = None,
        orientation: Literal['top', 'right'] = 'top',
    ):
        """\
        Draws brackets that represent groups of genes on the give axis.
        For best results, this axis is located on top of an image whose
        x axis contains gene names.

        The gene_groups_ax should share the x axis with the main ax.

        Eg: gene_groups_ax = fig.add_subplot(axs[0, 0], sharex=dot_ax)

        Parameters
        ----------
        gene_groups_ax
            In this axis the gene marks are drawn
        group_positions
            Each item in the list, should contain the start and end position that the
            bracket should cover.
            Eg. [(0, 4), (5, 8)] means that there are two brackets, one for the var_names (eg genes)
            in positions 0-4 and other for positions 5-8
        group_labels
            List of group labels
        left_adjustment
            adjustment to plot the bracket start slightly before or after the first gene position.
            If the value is negative the start is moved before.
        right_adjustment
            adjustment to plot the bracket end slightly before or after the last gene position
            If the value is negative the start is moved before.
        rotation
            rotation degrees for the labels. If not given, small labels (<4 characters) are not
            rotated, otherwise, they are rotated 90 degrees
        orientation
            location of the brackets. Either `top` or `right`
        Returns
        -------
        None
        """
        import matplotlib.patches as patches
        from matplotlib.path import Path

        # get the 'brackets' coordinates as lists of start and end positions

        left = [x[0] + left_adjustment for x in group_positions]
        right = [x[1] + right_adjustment for x in group_positions]

        # verts and codes are used by PathPatch to make the brackets
        verts = []
        codes = []
        if orientation == 'top':
            # rotate labels if any of them is longer than 4 characters
            if rotation is None and group_labels:
                if max([len(x) for x in group_labels]) > 4:
                    rotation = 90
                else:
                    rotation = 0
            for idx, (left_coor, right_coor) in enumerate(zip(left, right)):
                verts.append((left_coor, 0))  # lower-left
                verts.append((left_coor, 0.6))  # upper-left
                verts.append((right_coor, 0.6))  # upper-right
                verts.append((right_coor, 0))  # lower-right

                codes.append(Path.MOVETO)
                codes.append(Path.LINETO)
                codes.append(Path.LINETO)
                codes.append(Path.LINETO)

                group_x_center = left[idx] + float(right[idx] - left[idx]) / 2
                gene_groups_ax.text(
                    group_x_center,
                    1.1,
                    group_labels[idx],
                    ha='center',
                    va='bottom',
                    rotation=rotation,
                )
        else:
            top = left
            bottom = right
            for idx, (top_coor, bottom_coor) in enumerate(zip(top, bottom)):
                verts.append((0, top_coor))  # upper-left
                verts.append((0.4, top_coor))  # upper-right
                verts.append((0.4, bottom_coor))  # lower-right
                verts.append((0, bottom_coor))  # lower-left

                codes.append(Path.MOVETO)
                codes.append(Path.LINETO)
                codes.append(Path.LINETO)
                codes.append(Path.LINETO)

                diff = bottom[idx] - top[idx]
                group_y_center = top[idx] + float(diff) / 2
                if diff * 2 < len(group_labels[idx]):
                    # cut label to fit available space
                    group_labels[idx] = group_labels[idx][: int(diff * 2)] + "."
                gene_groups_ax.text(
                    1.1,
                    group_y_center,
                    group_labels[idx],
                    ha='right',
                    va='center',
                    rotation=270,
                    fontsize='small',
                )

        path = Path(verts, codes)

        patch = patches.PathPatch(path, facecolor='none', lw=1.5)

        gene_groups_ax.add_patch(patch)
        gene_groups_ax.grid(False)
        gene_groups_ax.axis('off')
        # remove y ticks
        gene_groups_ax.tick_params(axis='y', left=False, labelleft=False)
        # remove x ticks and labels
        gene_groups_ax.tick_params(
            axis='x', bottom=False, labelbottom=False, labeltop=False
        )

    def _update_var_groups(self):
        """
        checks if var_names is a dict. Is this is the cases, then set the
        correct values for var_group_labels and var_group_positions

        updates var_names, var_group_labels, var_group_positions

        Returns
        -------
        None

        """
        if isinstance(self.var_names, cabc.Mapping):
            if self.has_var_groups:
                logg.warning(
                    "`var_names` is a dictionary. This will reset the current "
                    "values of `var_group_labels` and `var_group_positions`."
                )
            var_group_labels = []
            _var_names = []
            var_group_positions = []
            start = 0
            for label, vars_list in self.var_names.items():
                if isinstance(vars_list, str):
                    vars_list = [vars_list]
                # use list() in case var_list is a numpy array or pandas series
                _var_names.extend(list(vars_list))
                var_group_labels.append(label)
                var_group_positions.append((start, start + len(vars_list) - 1))
                start += len(vars_list)
            self.var_names = _var_names
            self.var_group_labels = var_group_labels
            self.var_group_positions = var_group_positions
            self.has_var_groups = True

        elif isinstance(self.var_names, str):
            self.var_names = [self.var_names]


@_doc_params(common_plot_args=doc_common_plot_args)
class DotPlot(BasePlot):
    """\
    Allows the visualization of two values that are encoded as
    dot size and color. The size usually represents the fraction
    of cells (obs) that have a non-zero value for genes (var).

    For each var_name and each `groupby` category a dot is plotted.
    Each dot represents two values: mean expression within each category
    (visualized by color) and fraction of cells expressing the `var_name` in the
    category (visualized by the size of the dot). If `groupby` is not given,
    the dotplot assumes that all data belongs to a single category.

    .. note::
       A gene is considered expressed if the expression value in the `adata` (or
       `adata.raw`) is above the specified threshold which is zero by default.

    An example of dotplot usage is to visualize, for multiple marker genes,
    the mean value and the percentage of cells expressing the gene
    across multiple clusters.

    Parameters
    ----------
    {common_plot_args}
    title
        Title for the figure
    expression_cutoff
        Expression cutoff that is used for binarizing the gene expression and
        determining the fraction of cells expressing given genes. A gene is
        expressed only if the expression value is greater than this threshold.
    mean_only_expressed
        If True, gene expression is averaged only over the cells
        expressing the given genes.
    standard_scale
        Whether or not to standardize that dimension between 0 and 1,
        meaning for each variable or group,
        subtract the minimum and divide each by its maximum.

    **kwds
        Are passed to :func:`matplotlib.pyplot.scatter`.

    Examples
    -------
    >>> adata = sc.datasets.pbmc68k_reduced()
    >>> markers = ['C1QA', 'PSAP', 'CD79A', 'CD79B', 'CST3', 'LYZ']
    >>> sc.pl.DotPlot(adata, markers, groupby='bulk_labels').show()

    Using var_names as dict:

    >>> markers = {{'T-cell': 'CD3D', 'B-cell': 'CD79A', 'myeloid': 'CST3'}}
    >>> sc.pl.DotPlot(adata, markers, groupby='bulk_labels').show()

    See also
    --------
    :func:`~scanpy.pl.rank_genes_groups_dotplot`: to plot marker genes identified using the
    :func:`~scanpy.tl.rank_genes_groups` function.
    """

    DEFAULT_SAVE_PREFIX = 'dotplot_'
    # default style parameters
    DEFAULT_COLORMAP = 'winter'
    DEFAULT_COLOR_ON = 'dot'
    DEFAULT_DOT_MAX = None
    DEFAULT_DOT_MIN = None
    DEFAULT_SMALLEST_DOT = 0.0
    DEFAULT_LARGEST_DOT = 200.0
    DEFAULT_DOT_EDGECOLOR = None
    DEFAULT_DOT_EDGELW = None
    DEFAULT_SIZE_EXPONENT = 1.5

    # default legend parameters
    DEFAULT_SIZE_LEGEND_TITLE = 'Fraction of cells\nin group (%)'
    DEFAULT_COLOR_LEGEND_TITLE = 'Expression\nlevel in group'
    DEFAULT_LEGENDS_WIDTH = 1.5

    def __init__(
        self,
        adata: AnnData,
        var_names: Union[_VarNames, Mapping[str, _VarNames]],
        groupby: Union[str, Sequence[str]],
        use_raw: Optional[bool] = None,
        log: bool = False,
        num_categories: int = 7,
        categories_order: Optional[Sequence[str]] = None,
        title: Optional[str] = None,
        figsize: Optional[Tuple[float, float]] = None,
        gene_symbols: Optional[str] = None,
        var_group_positions: Optional[Sequence[Tuple[int, int]]] = None,
        var_group_labels: Optional[Sequence[str]] = None,
        var_group_rotation: Optional[float] = None,
        layer: Optional[str] = None,
        expression_cutoff: float = 0.0,
        mean_only_expressed: bool = False,
        standard_scale: Literal['var', 'group'] = None,
        dot_color_df: Optional[pd.DataFrame] = None,
        dot_size_df: Optional[pd.DataFrame] = None,
        ax: Optional[_AxesSubplot] = None,
        **kwds,
    ):
        BasePlot.__init__(
            self,
            adata,
            var_names,
            groupby,
            use_raw=use_raw,
            log=log,
            num_categories=num_categories,
            categories_order=categories_order,
            title=title,
            figsize=figsize,
            gene_symbols=gene_symbols,
            var_group_positions=var_group_positions,
            var_group_labels=var_group_labels,
            var_group_rotation=var_group_rotation,
            layer=layer,
            ax=ax,
            **kwds,
        )

        # for if category defined by groupby (if any) compute for each var_name
        # 1. the fraction of cells in the category having a value >expression_cutoff
        # 2. the mean value over the category

        # 1. compute fraction of cells having value > expression_cutoff
        # transform obs_tidy into boolean matrix using the expression_cutoff
        obs_bool = self.obs_tidy > expression_cutoff

        # compute the sum per group which in the boolean matrix this is the number
        # of values >expression_cutoff, and divide the result by the total number of
        # values in the group (given by `count()`)
        if dot_size_df is None:
            dot_size_df = (
                obs_bool.groupby(level=0).sum() / obs_bool.groupby(level=0).count()
            )

        if dot_color_df is None:
            # 2. compute mean expression value value
            if mean_only_expressed:
                dot_color_df = (
                    self.obs_tidy.mask(~obs_bool).groupby(level=0).mean().fillna(0)
                )
            else:
                dot_color_df = self.obs_tidy.groupby(level=0).mean()

            if standard_scale == 'group':
                dot_color_df = dot_color_df.sub(dot_color_df.min(1), axis=0)
                dot_color_df = dot_color_df.div(dot_color_df.max(1), axis=0).fillna(0)
            elif standard_scale == 'var':
                dot_color_df -= dot_color_df.min(0)
                dot_color_df = (dot_color_df / dot_color_df.max(0)).fillna(0)
            elif standard_scale is None:
                pass
            else:
                logg.warning('Unknown type for standard_scale, ignored')
        else:
            # check that both matrices have the same shape
            if dot_color_df.shape != dot_size_df.shape:
                logg.error(
                    "the given dot_color_df data frame has a different shape than"
                    "the data frame used for the dot size. Both data frames need"
                    "to have the same index and columns"
                )

            # Because genes (columns) can be duplicated (e.g. when the
            # same gene is reported as marker gene in two clusters)
            # they need to be removed first,
            # otherwise, the duplicated genes are further duplicated when reordering
            # Eg. A df with columns ['a', 'b', 'a'] after reordering columns
            # with df[['a', 'a', 'b']], results in a df with columns:
            # ['a', 'a', 'a', 'a', 'b']

            unique_var_names, unique_idx = np.unique(
                dot_color_df.columns, return_index=True
            )
            # remove duplicate columns
            if len(unique_var_names) != len(self.var_names):
                dot_color_df = dot_color_df.iloc[:, unique_idx]

            # get the same order for rows and columns in the dot_color_df
            # using the order from the doc_size_df
            dot_color_df = dot_color_df.loc[dot_size_df.index][dot_size_df.columns]

        self.dot_color_df = dot_color_df
        self.dot_size_df = dot_size_df

        # Set default style parameters
        self.cmap = self.DEFAULT_COLORMAP
        self.dot_max = self.DEFAULT_DOT_MAX
        self.dot_min = self.DEFAULT_DOT_MIN
        self.smallest_dot = self.DEFAULT_SMALLEST_DOT
        self.largest_dot = self.DEFAULT_LARGEST_DOT
        self.color_on = self.DEFAULT_COLOR_ON
        self.size_exponent = self.DEFAULT_SIZE_EXPONENT
        self.grid = False

        self.dot_edge_color = self.DEFAULT_DOT_EDGECOLOR
        self.dot_edge_lw = self.DEFAULT_DOT_EDGELW

        # set legend defaults
        self.color_legend_title = self.DEFAULT_COLOR_LEGEND_TITLE
        self.size_title = self.DEFAULT_SIZE_LEGEND_TITLE
        self.legends_width = self.DEFAULT_LEGENDS_WIDTH
        self.show_size_legend = True
        self.show_colorbar = True

    def style(
        self,
        cmap: str = DEFAULT_COLORMAP,
        color_on: Optional[Literal['dot', 'square']] = DEFAULT_COLOR_ON,
        dot_max: Optional[float] = DEFAULT_DOT_MAX,
        dot_min: Optional[float] = DEFAULT_DOT_MIN,
        smallest_dot: Optional[float] = DEFAULT_SMALLEST_DOT,
        largest_dot: Optional[float] = DEFAULT_LARGEST_DOT,
        dot_edge_color: Optional[ColorLike] = DEFAULT_DOT_EDGECOLOR,
        dot_edge_lw: Optional[float] = DEFAULT_DOT_EDGELW,
        size_exponent: Optional[float] = DEFAULT_SIZE_EXPONENT,
        grid: Optional[float] = False,
    ):
        """
        Modifies plot style

        Parameters
        ----------
        cmap
            String denoting matplotlib color map.
        color_on
            Options are 'dot' or 'square'. Be default the colomap is applied to
            the color of the dot. Optionally, the colormap can be applied to an
            square behind the dot, in which case the dot is transparent and only
            the edge is shown.
        dot_max
            If none, the maximum dot size is set to the maximum fraction value found
            (e.g. 0.6). If given, the value should be a number between 0 and 1.
            All fractions larger than dot_max are clipped to this value.
        dot_min
            If none, the minimum dot size is set to 0. If given,
            the value should be a number between 0 and 1.
            All fractions smaller than dot_min are clipped to this value.
        smallest_dot
            If none, the smallest dot has size 0.
            All expression fractions with `dot_min` are plotted with this size.
        largest_dot
            If none, the largest dot has size 200.
            All expression fractions with `dot_max` are plotted with this size.
        dot_edge_color
            Dot edge color. When `color_on='dot'` the default is no edge. When
            `color_on='square'`, edge color is white
        dot_edge_lw
            Dot edge line width. When `color_on='dot'` the default is no edge. When
            `color_on='square'`, line width = 1.5
        size_exponent
            Dot size is computed as:
            fraction  ** size exponent and afterwards scaled to match the
            `smallest_dot` and `largest_dot` size parameters.
            Using a different size exponent changes the relative sizes of the dots
            to each other.
        grid
            Set to true to show grid lines. By default grid lines are not shown.
            Further configuration of the grid lines can be achived directly on the
            returned ax.
        Returns
        -------
        DotPlot

        Examples
        -------
        >>> adata = sc.datasets.pbmc68k_reduced()
        >>> markers = ['C1QA', 'PSAP', 'CD79A', 'CD79B', 'CST3', 'LYZ']

        Change color map and apply it to the square behind the dot
        >>> sc.pl.DotPlot(adata, markers, groupby='bulk_labels')\
        ...               .style(cmap='RdBu_r', color_on='square').show()

        Add edge to dots
        >>> sc.pl.DotPlot(adata, markers, groupby='bulk_labels')\
        ...               .style(dot_edge_color='black',  dot_edge_lw=1).show()

        """
        self.cmap = cmap
        self.dot_max = dot_max
        self.dot_min = dot_min
        self.smallest_dot = smallest_dot
        self.largest_dot = largest_dot
        self.color_on = color_on
        self.size_exponent = size_exponent

        self.dot_edge_color = dot_edge_color
        self.dot_edge_lw = dot_edge_lw
        self.grid = grid
        return self

    def legend(
        self,
        show: Optional[bool] = True,
        show_size_legend: Optional[bool] = True,
        show_colorbar: Optional[bool] = True,
        size_title: Optional[str] = DEFAULT_SIZE_LEGEND_TITLE,
        colorbar_title: Optional[str] = DEFAULT_COLOR_LEGEND_TITLE,
        width: Optional[float] = DEFAULT_LEGENDS_WIDTH,
    ):
        """
        Configure legend parameters.

        Parameters
        ----------
        show
            Set to `False` to hide the default plot of the legends.
        show_size_legend
            Set to `False` to hide the the size legend
        show_colorbar
            Set to `False` to hide the the colorbar
        size_title
            Title for the dot size legend. Use "\n" to add line breaks.
        colorbar_title
            Title for the color bar. Use "\n" to add line breaks.
        width
            Width of the legends.

        Returns
        -------
        DotPlot

        Examples
        --------
        >>> adata = sc.datasets.pbmc68k_reduced()
        >>> markers = {{'T-cell': 'CD3D', 'B-cell': 'CD79A', 'myeloid': 'CST3'}}
        >>> dp = sc.pl.DotPlot(adata, markers, groupby='bulk_labels')
        >>> dp.legend(colorbar_title='log(UMI counts + 1)').show()
        """

        if not show:
            # turn of legends by setting width to 0
            self.legends_width = 0
        else:
            self.color_legend_title = colorbar_title
            self.size_title = size_title
            self.legends_width = width
            self.show_size_legend = show_size_legend
            self.show_colorbar = show_colorbar

        return self

    def _plot_size_legend(self, size_legend_ax: Axes):
        # for the dot size legend, use step between dot_max and dot_min
        # based on how different they are.
        diff = self.dot_max - self.dot_min
        if 0.3 < diff <= 0.6:
            step = 0.1
        elif diff <= 0.3:
            step = 0.05
        else:
            step = 0.2
        # a descending range that is afterwards inverted is used
        # to guarantee that dot_max is in the legend.
        size_range = np.arange(self.dot_max, self.dot_min, step * -1)[::-1]
        if self.dot_min != 0 or self.dot_max != 1:
            dot_range = self.dot_max - self.dot_min
            size_values = (size_range - self.dot_min) / dot_range
        else:
            size_values = size_range

        size = size_values ** self.size_exponent
        size = size * (self.largest_dot - self.smallest_dot) + self.smallest_dot

        # plot size bar
        size_legend_ax.scatter(
            np.arange(len(size)) + 0.5,
            np.repeat(0, len(size)),
            s=size,
            color='gray',
            edgecolor='black',
            zorder=100,
        )
        size_legend_ax.set_xticks(np.arange(len(size)) + 0.5)
        labels = [
            "{}".format(np.round((x * 100), decimals=0).astype(int)) for x in size_range
        ]
        size_legend_ax.set_xticklabels(labels, fontsize='small')

        # remove y ticks and labels
        size_legend_ax.tick_params(
            axis='y', left=False, labelleft=False, labelright=False
        )

        # remove surrounding lines
        size_legend_ax.spines['right'].set_visible(False)
        size_legend_ax.spines['top'].set_visible(False)
        size_legend_ax.spines['left'].set_visible(False)
        size_legend_ax.spines['bottom'].set_visible(False)
        size_legend_ax.grid(False)

        ymax = size_legend_ax.get_ylim()[1]
        size_legend_ax.set_ylim(-1.05 - self.largest_dot * 0.003, 4)
        size_legend_ax.set_title(self.size_title, y=ymax + 0.45, size='small')

        xmin, xmax = size_legend_ax.get_xlim()
        size_legend_ax.set_xlim(xmin - 0.15, xmax + 0.5)

    def _plot_legend(self, legend_ax, return_ax_dict, normalize):

        # to maintain the fixed height size of the legends, a
        # spacer of variable height is added at the bottom.
        # The structure for the legends is:
        # first row: variable space to keep the other rows of
        #            the same size (avoid stretching)
        # second row: legend for dot size
        # third row: spacer to avoid color and size legend titles to overlap
        # fourth row: colorbar

        cbar_legend_height = self.min_figure_height * 0.08
        size_legend_height = self.min_figure_height * 0.27
        spacer_height = self.min_figure_height * 0.3

        height_ratios = [
            self.height - size_legend_height - cbar_legend_height - spacer_height,
            size_legend_height,
            spacer_height,
            cbar_legend_height,
        ]
        fig, legend_gs = make_grid_spec(
            legend_ax, nrows=4, ncols=1, height_ratios=height_ratios,
        )

        if self.show_size_legend:
            size_legend_ax = fig.add_subplot(legend_gs[1])
            self._plot_size_legend(size_legend_ax)
            return_ax_dict['size_legend_ax'] = size_legend_ax

        if self.show_colorbar:
            color_legend_ax = fig.add_subplot(legend_gs[3])

            self._plot_colorbar(color_legend_ax, normalize)
            return_ax_dict['color_legend_ax'] = color_legend_ax

    def _mainplot(self, ax):
        # work on a copy of the dataframes. This is to avoid changes
        # on the original data frames after repetitive calls to the
        # DotPlot object, for example once with swap_axes and other without

        _color_df = self.dot_color_df.copy()
        _size_df = self.dot_size_df.copy()
        if self.var_names_idx_order is not None:
            _color_df = _color_df.iloc[:, self.var_names_idx_order]
            _size_df = _size_df.iloc[:, self.var_names_idx_order]

        if self.categories_order is not None:
            _color_df = _color_df.loc[self.categories_order, :]
            _size_df = _size_df.loc[self.categories_order, :]

        if self.are_axes_swapped:
            _size_df = _size_df.T
            _color_df = _color_df.T
        self.cmap = self.kwds.get('cmap', self.cmap)
        if 'cmap' in self.kwds:
            del self.kwds['cmap']

        normalize, dot_min, dot_max = self._dotplot(
            _size_df,
            _color_df,
            ax,
            cmap=self.cmap,
            dot_max=self.dot_max,
            dot_min=self.dot_min,
            color_on=self.color_on,
            edge_color=self.dot_edge_color,
            edge_lw=self.dot_edge_lw,
            smallest_dot=self.smallest_dot,
            largest_dot=self.largest_dot,
            size_exponent=self.size_exponent,
            grid=self.grid,
            **self.kwds,
        )

        self.dot_min, self.dot_max = dot_min, dot_max
        return normalize

    @staticmethod
    def _dotplot(
        dot_size,
        dot_color,
        dot_ax,
        cmap: str = 'Reds',
        color_on: Optional[str] = 'dot',
        y_label: Optional[str] = None,
        dot_max: Optional[float] = None,
        dot_min: Optional[float] = None,
        standard_scale: Literal['var', 'group'] = None,
        smallest_dot: Optional[float] = 0.0,
        largest_dot: Optional[float] = 200,
        size_exponent: Optional[float] = 2,
        edge_color: Optional[ColorLike] = None,
        edge_lw: Optional[float] = None,
        grid: Optional[bool] = False,
        **kwds,
    ):
        """\
        Makes a *dot plot* given two data frames, one containing
        the doc size and other containing the dot color. The indices and
        columns of the data frame are used to label the output image

        The dots are plotted
        using matplotlib.pyplot.scatter. Thus, additional arguments can be passed.
        Parameters
        ----------
        dot_size: Data frame containing the dot_size.
        dot_color: Data frame containing the dot_color, should have the same,
                shape, columns and indices as dot_size.
        dot_ax: matplotlib axis
        y_lebel:
        cmap
            String denoting matplotlib color map.
        color_on
            Options are 'dot' or 'square'. Be default the colomap is applied to
            the color of the dot. Optionally, the colormap can be applied to an
            square behind the dot, in which case the dot is transparent and only
            the edge is shown.
        y_label: String. Label for y axis
        dot_max
            If none, the maximum dot size is set to the maximum fraction value found
            (e.g. 0.6). If given, the value should be a number between 0 and 1.
            All fractions larger than dot_max are clipped to this value.
        dot_min
            If none, the minimum dot size is set to 0. If given,
            the value should be a number between 0 and 1.
            All fractions smaller than dot_min are clipped to this value.
        standard_scale
            Whether or not to standardize that dimension between 0 and 1,
            meaning for each variable or group,
            subtract the minimum and divide each by its maximum.
        smallest_dot
            If none, the smallest dot has size 0.
            All expression levels with `dot_min` are plotted with this size.
        edge_color
            Dot edge color. When `color_on='dot'` the default is no edge. When
            `color_on='square'`, edge color is white
        edge_lw
            Dot edge line width. When `color_on='dot'` the default is no edge. When
            `color_on='square'`, line width = 1.5
        grid
            Adds a grid to the plot
        **kwds
            Are passed to :func:`matplotlib.pyplot.scatter`.

        Returns
        -------
        matplotlib.colors.Normalize, dot_min, dot_max

        """
        assert dot_size.shape == dot_color.shape, (
            'please check that dot_size ' 'and dot_color dataframes have the same shape'
        )

        assert list(dot_size.index) == list(dot_color.index), (
            'please check that dot_size ' 'and dot_color dataframes have the same index'
        )

        assert list(dot_size.columns) == list(dot_color.columns), (
            'please check that the dot_size '
            'and dot_color dataframes have the same columns'
        )

        if standard_scale == 'group':
            dot_color = dot_color.sub(dot_color.min(1), axis=0)
            dot_color = dot_color.div(dot_color.max(1), axis=0).fillna(0)
        elif standard_scale == 'var':
            dot_color -= dot_color.min(0)
            dot_color = (dot_color / dot_color.max(0)).fillna(0)
        elif standard_scale is None:
            pass

        # make scatter plot in which
        # x = var_names
        # y = groupby category
        # size = fraction
        # color = mean expression

        y, x = np.indices(dot_color.shape)
        y = y.flatten() + 0.5
        x = x.flatten() + 0.5
        frac = dot_size.values.flatten()
        mean_flat = dot_color.values.flatten()
        cmap = pl.get_cmap(kwds.get('cmap', cmap))
        if 'cmap' in kwds:
            del kwds['cmap']
        if dot_max is None:
            dot_max = np.ceil(max(frac) * 10) / 10
        else:
            if dot_max < 0 or dot_max > 1:
                raise ValueError("`dot_max` value has to be between 0 and 1")
        if dot_min is None:
            dot_min = 0
        else:
            if dot_min < 0 or dot_min > 1:
                raise ValueError("`dot_min` value has to be between 0 and 1")

        if dot_min != 0 or dot_max != 1:
            # clip frac between dot_min and  dot_max
            frac = np.clip(frac, dot_min, dot_max)
            old_range = dot_max - dot_min
            # re-scale frac between 0 and 1
            frac = (frac - dot_min) / old_range

        size = frac ** size_exponent
        # rescale size to match smallest_dot and largest_dot
        size = size * (largest_dot - smallest_dot) + smallest_dot

        import matplotlib.colors

        normalize = matplotlib.colors.Normalize(
            vmin=kwds.get('vmin'), vmax=kwds.get('vmax')
        )

        if color_on == 'square':
            edge_color = 'white' if edge_color is None else edge_color
            edge_lw = 1.5 if edge_lw is None else edge_lw
            # makes first a 'matrixplot' (squares with the asigned colormap
            dot_ax.pcolor(dot_color.values, cmap=cmap, norm=normalize)
            for axis in ['top', 'bottom', 'left', 'right']:
                dot_ax.spines[axis].set_linewidth(1.5)
            kwds = fix_kwds(
                kwds,
                s=size,
                cmap=cmap,
                norm=None,
                linewidth=edge_lw,
                facecolor='none',
                edgecolor=edge_color,
            )
            dot_ax.scatter(x, y, **kwds)
        else:
            edge_color = 'none' if edge_color is None else edge_color
            edge_lw = 0.5 if edge_lw is None else edge_lw

            color = cmap(normalize(mean_flat))
            kwds = fix_kwds(
                kwds,
                s=size,
                cmap=cmap,
                color=color,
                norm=None,
                linewidth=edge_lw,
                edgecolor=edge_color,
            )

            dot_ax.scatter(x, y, **kwds)

        y_ticks = np.arange(dot_color.shape[0]) + 0.5
        dot_ax.set_yticks(y_ticks)
        dot_ax.set_yticklabels(
            [dot_color.index[idx] for idx, _ in enumerate(y_ticks)], minor=False
        )

        x_ticks = np.arange(dot_color.shape[1]) + 0.5
        dot_ax.set_xticks(x_ticks)
        dot_ax.set_xticklabels(
            [dot_color.columns[idx] for idx, _ in enumerate(x_ticks)],
            rotation=90,
            ha='center',
            minor=False,
        )
        dot_ax.tick_params(axis='both', labelsize='small')
        dot_ax.grid(False)
        dot_ax.set_ylabel(y_label)

        # to be consistent with the heatmap plot, is better to
        # invert the order of the y-axis, such that the first group is on
        # top
        dot_ax.set_ylim(dot_color.shape[0], 0)
        dot_ax.set_xlim(0, dot_color.shape[1])

        if color_on == 'dot':
            # add more distance to the x and y lims with the color is on the
            # dots
            dot_ax.set_ylim(dot_color.shape[0] + 0.5, -0.5)

            dot_ax.set_xlim(-0.3, dot_color.shape[1] + 0.3)

        if grid:
            dot_ax.grid(True, color='gray', linewidth=0.1)
            dot_ax.set_axisbelow(True)

        return normalize, dot_min, dot_max


@_doc_params(common_plot_args=doc_common_plot_args)
class MatrixPlot(BasePlot):
    """\
    Allows the visualization of two values that are encoded as
    dot size and color. The size usually represents the fraction
    of cells (obs) that have a non-zero value for genes (var).

    For each var_name and each `groupby` category a dot is plotted.
    Each dot represents two values: mean expression within each category
    (visualized by color) and fraction of cells expressing the `var_name` in the
    category (visualized by the size of the dot). If `groupby` is not given,
    the dotplot assumes that all data belongs to a single category.

    .. note::
       A gene is considered expressed if the expression value in the `adata` (or
       `adata.raw`) is above the specified threshold which is zero by default.

    An example of dotplot usage is to visualize, for multiple marker genes,
    the mean value and the percentage of cells expressing the gene
    across multiple clusters.

    Parameters
    ----------
    {common_plot_args}
    title
        Title for the figure
    expression_cutoff
        Expression cutoff that is used for binarizing the gene expression and
        determining the fraction of cells expressing given genes. A gene is
        expressed only if the expression value is greater than this threshold.
    mean_only_expressed
        If True, gene expression is averaged only over the cells
        expressing the given genes.
    standard_scale
        Whether or not to standardize that dimension between 0 and 1,
        meaning for each variable or group,
        subtract the minimum and divide each by its maximum.
    values_df
        Optionally, a dataframe with the values to plot can be given. The
        index should be the grouby categories and the columns the genes names.

    **kwds
        Are passed to :func:`matplotlib.pyplot.scatter`.

    Examples
    -------
    >>> adata = sc.datasets.pbmc68k_reduced()
    >>> markers = ['C1QA', 'PSAP', 'CD79A', 'CD79B', 'CST3', 'LYZ']
    >>> sc.pl.DotPlot(adata, markers, groupby='bulk_labels').show()

    Using var_names as dict:

    >>> markers = {{'T-cell': 'CD3D', 'B-cell': 'CD79A', 'myeloid': 'CST3'}}
    >>> sc.pl.DotPlot(adata, markers, groupby='bulk_labels').show()

    See also
    --------
    :func:`~scanpy.pl.rank_genes_groups_dotplot`: to plot marker genes identified using the
    :func:`~scanpy.tl.rank_genes_groups` function.
    """

    DEFAULT_SAVE_PREFIX = 'matrixplot_'

    # default style parameters
    DEFAULT_COLORMAP = rcParams['image.cmap']
    DEFAULT_EDGE_COLOR = 'gray'
    DEFAULT_EDGE_LW = 0.1

    def __init__(
        self,
        adata: AnnData,
        var_names: Union[_VarNames, Mapping[str, _VarNames]],
        groupby: Union[str, Sequence[str]],
        use_raw: Optional[bool] = None,
        log: bool = False,
        num_categories: int = 7,
        categories_order: Optional[Sequence[str]] = None,
        title: Optional[str] = None,
        figsize: Optional[Tuple[float, float]] = None,
        gene_symbols: Optional[str] = None,
        var_group_positions: Optional[Sequence[Tuple[int, int]]] = None,
        var_group_labels: Optional[Sequence[str]] = None,
        var_group_rotation: Optional[float] = None,
        layer: Optional[str] = None,
        standard_scale: Literal['var', 'group'] = None,
        ax: Optional[_AxesSubplot] = None,
        values_df: Optional[pd.DataFrame] = None,
        **kwds,
    ):
        BasePlot.__init__(
            self,
            adata,
            var_names,
            groupby,
            use_raw=use_raw,
            log=log,
            num_categories=num_categories,
            categories_order=categories_order,
            title=title,
            figsize=figsize,
            gene_symbols=gene_symbols,
            var_group_positions=var_group_positions,
            var_group_labels=var_group_labels,
            var_group_rotation=var_group_rotation,
            layer=layer,
            ax=ax,
            **kwds,
        )

        if values_df is None:
            # compute mean value
            values_df = self.obs_tidy.groupby(level=0).mean()

            if standard_scale == 'group':
                values_df = values_df.sub(values_df.min(1), axis=0)
                values_df = values_df.div(values_df.max(1), axis=0).fillna(0)
            elif standard_scale == 'var':
                values_df -= values_df.min(0)
                values_df = (values_df / values_df.max(0)).fillna(0)
            elif standard_scale is None:
                pass
            else:
                logg.warning('Unknown type for standard_scale, ignored')

        self.values_df = values_df

        self.cmap = self.DEFAULT_COLORMAP
        self.edge_color = self.DEFAULT_EDGE_COLOR
        self.edge_lw = self.DEFAULT_EDGE_LW

    def style(
        self,
        cmap: str = DEFAULT_COLORMAP,
        edge_color: Optional[ColorLike] = DEFAULT_EDGE_COLOR,
        edge_lw: Optional[float] = DEFAULT_EDGE_LW,
    ):
        """
        Modifies plot graphical parameters

        Parameters
        ----------
        cmap
            String denoting matplotlib color map.
        edge_color
            Edge color betweem the squares of matrix plot. Default is gray
        edge_lw
            Edge line width.

        Returns
        -------
        MatrixPlot

        Examples
        -------
        >>> adata = sc.datasets.pbmc68k_reduced()
        >>> markers = ['C1QA', 'PSAP', 'CD79A', 'CD79B', 'CST3', 'LYZ']

        Change color map and turn off edges
        >>> sc.pl.MatrixPlot(adata, markers, groupby='bulk_labels')\
        ...               .style(cmap='Blues', edge_color='none').show()

        """

        self.cmap = cmap
        self.edge_color = edge_color
        self.edge_lw = edge_lw

        return self

    def _mainplot(self, ax):
        # work on a copy of the dataframes. This is to avoid changes
        # on the original data frames after repetitive calls to the
        # MatrixPlot object, for example once with swap_axes and other without

        _color_df = self.values_df.copy()
        if self.var_names_idx_order is not None:
            _color_df = _color_df.iloc[:, self.var_names_idx_order]

        if self.categories_order is not None:
            _color_df = _color_df.loc[self.categories_order, :]

        if self.are_axes_swapped:
            _color_df = _color_df.T
        cmap = pl.get_cmap(self.kwds.get('cmap', self.cmap))
        if 'cmap' in self.kwds:
            del self.kwds['cmap']

        import matplotlib.colors

        normalize = matplotlib.colors.Normalize(
            vmin=self.kwds.get('vmin'), vmax=self.kwds.get('vmax')
        )

        for axis in ['top', 'bottom', 'left', 'right']:
            ax.spines[axis].set_linewidth(1.5)

        kwds = fix_kwds(
            self.kwds,
            cmap=cmap,
            edgecolor=self.edge_color,
            linewidth=self.edge_lw,
            norm=normalize,
        )
        __ = ax.pcolor(_color_df, **kwds)

        y_labels = _color_df.index
        x_labels = _color_df.columns

        y_ticks = np.arange(len(y_labels)) + 0.5
        ax.set_yticks(y_ticks)
        ax.set_yticklabels(y_labels)

        x_ticks = np.arange(len(x_labels)) + 0.5
        ax.set_xticks(x_ticks)
        ax.set_xticklabels(x_labels, rotation=90, ha='center', minor=False)

        ax.tick_params(axis='both', labelsize='small')
        ax.grid(False)

        # to be consistent with the heatmap plot, is better to
        # invert the order of the y-axis, such that the first group is on
        # top
        ax.set_ylim(len(y_labels), 0)
        ax.set_xlim(0, len(x_labels))

        return normalize


@_doc_params(common_plot_args=doc_common_plot_args)
class StackedViolin(BasePlot):
    """\
    Stacked violin plots.

    Makes a compact image composed of individual violin plots
    (from :func:`~seaborn.violinplot`) stacked on top of each other.
    Useful to visualize gene expression per cluster.

    Wraps :func:`seaborn.violinplot` for :class:`~anndata.AnnData`.

    Parameters
    ----------
    {common_plot_args}
    title
        Title for the figure
    stripplot
        Add a stripplot on top of the violin plot.
        See :func:`~seaborn.stripplot`.
    jitter
        Add jitter to the stripplot (only when stripplot is True)
        See :func:`~seaborn.stripplot`.
    size
        Size of the jitter points.
    order
        Order in which to show the categories. Note: if `dendrogram=True`
        the categories order will be given by the dendrogram and `order`
        will be ignored.
    scale
        The method used to scale the width of each violin.
        If 'width' (the default), each violin will have the same width.
        If 'area', each violin will have the same area.
        If 'count', a violin’s width corresponds to the number of observations.
    row_palette
        The row palette determines the colors to use for the stacked violins.
        The value should be a valid seaborn or matplotlib palette name
        (see :func:`~seaborn.color_palette`).
        Alternatively, a single color name or hex value can be passed,
        e.g. `'red'` or `'#cc33ff'`.
    standard_scale
        Whether or not to standardize a dimension between 0 and 1,
        meaning for each variable or observation,
        subtract the minimum and divide each by its maximum.
    swap_axes
         By default, the x axis contains `var_names` (e.g. genes) and the y axis the `groupby` categories.
         By setting `swap_axes` then x are the `groupby` categories and y the `var_names`. When swapping
         axes var_group_positions are no longer used
    **kwds
        Are passed to :func:`~seaborn.violinplot`.

    Examples
    -------
    >>> import scanpy as sc
    >>> adata = sc.datasets.pbmc68k_reduced()
    >>> markers = ['C1QA', 'PSAP', 'CD79A', 'CD79B', 'CST3', 'LYZ']
    >>> sc.pl.StackedViolin(adata, markers, groupby='bulk_labels', dendrogram=True)

    Using var_names as dict:

    >>> markers = {{'T-cell': 'CD3D', 'B-cell': 'CD79A', 'myeloid': 'CST3'}}
    >>> sc.pl.StackedViolin(adata, markers, groupby='bulk_labels', dendrogram=True)

    See also
    --------
    :func:`~scanpy.tl.violin` and
    rank_genes_groups_stacked_violin: to plot marker genes identified using the :func:`~scanpy.tl.rank_genes_groups` function.
    """

    DEFAULT_SAVE_PREFIX = 'stacked_violin_'

    DEFAULT_COLORMAP = 'Reds'
    DEFAULT_STRIPPLOT = False
    DEFAULT_JITTER = False
    DEFAULT_JITTER_SIZE = 1
    DEFAULT_LINE_WIDTH = 0.0
    DEFAULT_ROW_PALETTE = 'muted'
    DEFAULT_SCALE = 'width'
    DEFAULT_PLOT_YTICKLABELS = False
    DEFAULT_YLIM = None

    def __init__(
        self,
        adata: AnnData,
        var_names: Union[_VarNames, Mapping[str, _VarNames]],
        groupby: Union[str, Sequence[str]],
        use_raw: Optional[bool] = None,
        log: bool = False,
        num_categories: int = 7,
        categories_order: Optional[Sequence[str]] = None,
        title: Optional[str] = None,
        figsize: Optional[Tuple[float, float]] = None,
        gene_symbols: Optional[str] = None,
        var_group_positions: Optional[Sequence[Tuple[int, int]]] = None,
        var_group_labels: Optional[Sequence[str]] = None,
        var_group_rotation: Optional[float] = None,
        layer: Optional[str] = None,
        standard_scale: Literal['var', 'group'] = None,
        ax: Optional[_AxesSubplot] = None,
        **kwds,
    ):
        BasePlot.__init__(
            self,
            adata,
            var_names,
            groupby,
            use_raw=use_raw,
            log=log,
            num_categories=num_categories,
            categories_order=categories_order,
            title=title,
            figsize=figsize,
            gene_symbols=gene_symbols,
            var_group_positions=var_group_positions,
            var_group_labels=var_group_labels,
            var_group_rotation=var_group_rotation,
            layer=layer,
            ax=ax,
            **kwds,
        )

        if standard_scale == 'obs':
            self.obs_tidy = self.obs_tidy.sub(self.obs_tidy.min(1), axis=0)
            self.obs_tidy = self.obs_tidy.div(self.obs_tidy.max(1), axis=0).fillna(0)
        elif standard_scale == 'var':
            self.obs_tidy -= self.obs_tidy.min(0)
            self.obs_tidy = (self.obs_tidy / self.obs_tidy.max(0)).fillna(0)
        elif standard_scale is None:
            pass
        else:
            logg.warning('Unknown type for standard_scale, ignored')

        # Set default style parameters
        self.cmap = self.DEFAULT_COLORMAP
        self.row_palette = self.DEFAULT_ROW_PALETTE
        self.stripplot = self.DEFAULT_STRIPPLOT
        self.jitter = self.DEFAULT_JITTER
        self.jitter_size = self.DEFAULT_JITTER_SIZE
        self.plot_yticklabels = self.DEFAULT_PLOT_YTICKLABELS
        self.ylim = self.DEFAULT_YLIM

        # set by default the violin plot cut=0 to limit the extend
        # of the violin plot as this produces better plots that wont extend
        # to negative values for example. From seaborn.violin documentation:
        #
        # cut: Distance, in units of bandwidth size, to extend the density past
        # the extreme datapoints. Set to 0 to limit the violin range within
        # the range of the observed data (i.e., to have the same effect as
        # trim=True in ggplot.
        self.kwds.setdefault('cut', 0)
        self.kwds.setdefault('inner')

        self.kwds['linewidth'] = self.DEFAULT_LINE_WIDTH
        self.kwds['scale'] = self.DEFAULT_SCALE

    def style(
        self,
        cmap: str = DEFAULT_COLORMAP,
        stripplot: Optional[bool] = DEFAULT_STRIPPLOT,
        jitter: Optional[Union[float, bool]] = DEFAULT_JITTER,
        jitter_size: Optional[int] = DEFAULT_JITTER_SIZE,
        linewidth: Optional[float] = DEFAULT_LINE_WIDTH,
        row_palette: Optional[str] = DEFAULT_ROW_PALETTE,
        scale: Optional[Literal['area', 'count', 'width']] = DEFAULT_SCALE,
        yticklabels: Optional[bool] = DEFAULT_PLOT_YTICKLABELS,
        ylim: Optional[Tuple[float, float]] = DEFAULT_YLIM,
    ):
        """
        Modifies plot graphical parameters

        Parameters
        ----------
        cmap
            String denoting matplotlib color map.
        stripplot
            Add a stripplot on top of the violin plot.
            See :func:`~seaborn.stripplot`.
        jitter
            Add jitter to the stripplot (only when stripplot is True)
            See :func:`~seaborn.stripplot`.
        jitter_size
            Size of the jitter points.
        linewidth
            linewidth for the violin plots.
        row_palette
            The row palette determines the colors to use for the stacked violins.
            The value should be a valid seaborn or matplotlib palette name
            (see :func:`~seaborn.color_palette`).
            Alternatively, a single color name or hex value can be passed,
            e.g. `'red'` or `'#cc33ff'`.
        scale
            The method used to scale the width of each violin.
            If 'width' (the default), each violin will have the same width.
            If 'area', each violin will have the same area.
            If 'count', a violin’s width corresponds to the number of observations.
        yticklabels
            Because the plots are on top of each other the yticks labels tend to
            overlap and are not plotted. Set to true to view the labels.
        ylim
            minimum and maximum values for the y-axis. If set. All rows will have
            the same y-axis range. Example: ylim=(0, 5)

        Returns
        -------
        StackedViolin

        Examples
        -------
        >>> adata = sc.datasets.pbmc68k_reduced()
        >>> markers = ['C1QA', 'PSAP', 'CD79A', 'CD79B', 'CST3', 'LYZ']

        Change color map and turn off edges
        >>> sc.pl.MatrixPlot(adata, markers, groupby='bulk_labels')\
        ...               .style(row_palette='Blues', linewisth=0).show()

        """

        self.cmap = cmap
        self.row_palette = row_palette
        self.kwds['color'] = self.row_palette
        self.stripplot = stripplot
        self.jitter = jitter
        self.jitter_size = jitter_size
        self.plot_yticklabels = yticklabels
        self.ylim = ylim

        self.kwds['linewidth'] = linewidth
        self.kwds['scale'] = scale

        return self

    def _mainplot(self, ax):
        # to make the stacked violin plots, the
        # `ax` is subdivided horizontally and in each horizontal sub ax
        # a seaborn violin plot is added.

        # work on a copy of the dataframes. This is to avoid changes
        # on the original data frames after repetitive calls to the
        # StackedViolin object, for example once with swap_axes and other without
        _matrix = self.obs_tidy.copy()

        if self.var_names_idx_order is not None:
            _matrix = _matrix.iloc[:, self.var_names_idx_order]

        if self.categories_order is not None:
            _matrix.index = _matrix.index.reorder_categories(
                self.categories_order, ordered=True
            )

        # get mean values for color and transform to color values
        # using colormap
        _color_df = _matrix.groupby(level=0).median()
        if self.are_axes_swapped:
            _color_df = _color_df.T
        import matplotlib.colors

        norm = matplotlib.colors.Normalize(
            vmin=self.kwds.get('vmin'), vmax=self.kwds.get('vmax')
        )
        cmap = pl.get_cmap(self.kwds.get('cmap', self.cmap))
        if 'cmap' in self.kwds:
            del self.kwds['cmap']
        colormap_array = cmap(norm(_color_df.values))
        spacer_size = 0.5
        self._make_rows_of_violinplots(
            ax, _matrix, colormap_array, _color_df, spacer_size
        )

        # turn on axis for `ax` as this is turned off
        # by make_grid_spec when the axis is subdivided earlier.
        ax.set_frame_on(True)
        ax.axis('on')
        ax.patch.set_alpha(0.0)

        # add tick labels
        ax.set_ylim(_color_df.shape[0] + spacer_size, 0 - spacer_size)
        ax.set_xlim(0 - spacer_size, _color_df.shape[1] + spacer_size)

        y_ticks = np.arange(_color_df.shape[0]) + 0.5
        ax.set_yticks(y_ticks)
        ax.set_yticklabels(
            [_color_df.index[idx] for idx, _ in enumerate(y_ticks)], minor=False
        )

        x_ticks = np.arange(_color_df.shape[1]) + 0.5
        ax.set_xticks(x_ticks)
        labels = _color_df.columns
        ax.set_xticklabels(labels, minor=False, ha='center')
        # rotate x tick labels if they are longer than 2 characters
        if max([len(x) for x in labels]) > 2:
            ax.tick_params(axis='x', labelrotation=90)
        ax.tick_params(axis='both', labelsize='small')
        ax.grid(False)

        return norm

    def _make_rows_of_violinplots(
        self, ax, _matrix, colormap_array, _color_df, spacer_size
    ):
        import seaborn as sns  # Slow import, only import if called

        row_palette = self.kwds.get('color', self.row_palette)
        if 'color' in self.kwds:
            del self.kwds['color']
        if row_palette is not None:
            if is_color_like(row_palette):
                row_colors = [row_palette] * _color_df.shape[0]
            else:
                row_colors = sns.color_palette(row_palette, n_colors=_color_df.shape[0])
        else:
            row_colors = [None] * _color_df.shape[0]

        # All columns should have a unique name, yet, frequently
        # gene names are repeated in self.var_names,  otherwise the
        # violin plot will not distinguish those genes
        _matrix.columns = [f"{x}_{idx}" for idx, x in enumerate(_matrix.columns)]

        # transform the  dataframe into a dataframe having three columns:
        # the categories name (from groupby),
        # the gene name
        # the expression value
        # This format is convenient to aggregate per gene or per category
        # while making the violin plots.

        df = (
            pd.DataFrame(_matrix.stack(dropna=False))
            .reset_index()
            .rename(
                columns={
                    'level_1': 'genes',
                    _matrix.index.name: 'categories',
                    0: 'values',
                }
            )
        )
        df['genes'] = df['genes'].astype('category').cat.reorder_categories(_matrix.columns)
        df['categories'] = df['categories'].astype('category').cat.reorder_categories(
             _matrix.index.categories)

        # the ax need to be subdivided
        # define a layout of nrows = len(categories) rows
        # each row is one violin plot.
        num_rows, num_cols = _color_df.shape
        height_ratios = [spacer_size] + [1] * num_rows + [spacer_size]
        width_ratios = [spacer_size] + [1] * num_cols + [spacer_size]

        fig, gs = make_grid_spec(
            ax,
            nrows=num_rows + 2,
            ncols=num_cols + 2,
            hspace=0,
            wspace=0,
            height_ratios=height_ratios,
            width_ratios=width_ratios,
        )

        axs_list = []
        for idx, row_label in enumerate(_color_df.index):

            row_ax = fig.add_subplot(gs[idx + 1, 1:-1])
            row_ax.axis('off')
            axs_list.append(row_ax)

            if row_colors[idx] is None:
                palette_colors = colormap_array[idx, :]
            else:
                palette_colors = None

            if not self.are_axes_swapped:
                x = 'genes'
                _df = df[df.categories == row_label]
            else:
                x = 'categories'
                _df = df[df.genes == row_label]
            row_ax = sns.violinplot(
                x=x,
                y='values',
                data=_df,
                orient='vertical',
                ax=row_ax,
                palette=palette_colors,
                color=row_colors[idx],
                **self.kwds,
            )

            if self.stripplot:
                row_ax = sns.stripplot(
                    x=x,
                    y='values',
                    data=_df,
                    jitter=self.jitter,
                    color='black',
                    size=self.jitter_size,
                    ax=row_ax,
                )

            self._setup_violin_axes_ticks(row_ax)

    def _setup_violin_axes_ticks(self, row_ax):
        """
        Configures each of the violin plot axes ticks like remove or add labels etc.

        """
        # remove the default seaborn grids because in such a compact
        # plot are unnecessary
        row_ax.grid(False)
        if self.ylim is not None:
            row_ax.set_ylim(self.ylim)
        if self.log:
            row_ax.set_yscale('log')
        if self.plot_yticklabels:
            row_ax.tick_params(
                axis='y',
                left=True,
                right=False,
                labelright=False,
                labelleft=True,
                labelsize='x-small',
                length=1,
                pad=1,
            )
        else:
            # remove labels
            row_ax.set_yticklabels([])
            row_ax.tick_params(
                axis='y', left=False, right=False,
            )

        row_ax.set_ylabel('')

        row_ax.set_xlabel('')

        row_ax.set_xticklabels([])
        row_ax.tick_params(
            axis='x', bottom=False, top=False, labeltop=False, labelbottom=False,
        )


doc_common_groupby_plot_args = """\
title
    Title for the figure
colorbar_title
    Title for the color bar. New line character (\\n) can be used.
cmap
    String denoting matplotlib color map.
standard_scale
    Whether or not to standardize the given dimension between 0 and 1, meaning for 
    each variable or group, subtract the minimum and divide each by its maximum.
swap_axes
     By default, the x axis contains `var_names` (e.g. genes) and the y axis
     the `groupby` categories. By setting `swap_axes` then x are the
     `groupby` categories and y the `var_names`.
return_fig
    Returns :class:`DotPlot` object. Useful for fine-tuning
    the plot. Takes precedence over `show=False`.

"""


@_doc_params(
    show_save_ax=doc_show_save_ax,
    common_plot_args=doc_common_plot_args,
    groupby_plots_args=doc_common_groupby_plot_args,
)
def dotplot(
    adata: AnnData,
    var_names: Union[_VarNames, Mapping[str, _VarNames]],
    groupby: Union[str, Sequence[str]],
    use_raw: Optional[bool] = None,
    log: bool = False,
    num_categories: int = 7,
    expression_cutoff: float = 0.0,
    mean_only_expressed: bool = False,
    cmap: str = 'Reds',
    dot_max: Optional[float] = None,
    dot_min: Optional[float] = None,
    standard_scale: Optional[Literal['var', 'group']] = None,
    smallest_dot: Optional[float] = DotPlot.DEFAULT_SMALLEST_DOT,
    title: Optional[str] = None,
    colorbar_title: Optional[str] = DotPlot.DEFAULT_COLOR_LEGEND_TITLE,
    size_title: Optional[str] = DotPlot.DEFAULT_SIZE_LEGEND_TITLE,
    figsize: Optional[Tuple[float, float]] = None,
    dendrogram: Union[bool, str] = False,
    gene_symbols: Optional[str] = None,
    var_group_positions: Optional[Sequence[Tuple[int, int]]] = None,
    var_group_labels: Optional[Sequence[str]] = None,
    var_group_rotation: Optional[float] = None,
    layer: Optional[str] = None,
    swap_axes: Optional[bool] = False,
    dot_color_df: Optional[pd.DataFrame] = None,
    show: Optional[bool] = None,
    save: Union[str, bool, None] = None,
    ax: Optional[_AxesSubplot] = None,
    return_fig: Optional[bool] = False,
    **kwds,
) -> Union[DotPlot, dict, None]:
    """\
    Makes a *dot plot* of the expression values of `var_names`.

    For each var_name and each `groupby` category a dot is plotted.
    Each dot represents two values: mean expression within each category
    (visualized by color) and fraction of cells expressing the `var_name` in the
    category (visualized by the size of the dot). If `groupby` is not given,
    the dotplot assumes that all data belongs to a single category.

    .. note::
       A gene is considered expressed if the expression value in the `adata` (or
       `adata.raw`) is above the specified threshold which is zero by default.

    An example of dotplot usage is to visualize, for multiple marker genes,
    the mean value and the percentage of cells expressing the gene
    across  multiple clusters.

    This function provides a convenient interface to the :class:`DotPlot`
    class. If you need more flexibility, you should use :class:`DotPlot` directly.

    Parameters
    ----------
    {common_plot_args}
    {groupby_plots_args}
    size_title
        Title for the size legend. New line character (\\n) can be used.
    expression_cutoff
        Expression cutoff that is used for binarizing the gene expression and
        determining the fraction of cells expressing given genes. A gene is
        expressed only if the expression value is greater than this threshold.
    mean_only_expressed
        If True, gene expression is averaged only over the cells
        expressing the given genes.
    dot_max
        If none, the maximum dot size is set to the maximum fraction value found
        (e.g. 0.6). If given, the value should be a number between 0 and 1.
        All fractions larger than dot_max are clipped to this value.
    dot_min
        If none, the minimum dot size is set to 0. If given,
        the value should be a number between 0 and 1.
        All fractions smaller than dot_min are clipped to this value.
    smallest_dot
        If none, the smallest dot has size 0.
        All expression levels with `dot_min` are plotted with this size.
    {show_save_ax}
    **kwds
        Are passed to :func:`matplotlib.pyplot.scatter`.

    Returns
    -------
    If `return_fig` is `True`, returns a :class:`DotPlot` object,
    else if `show` is false, return axes dict

    Examples
    -------
    >>> import scanpy as sc
    >>> adata = sc.datasets.pbmc68k_reduced()
    >>> markers = ['C1QA', 'PSAP', 'CD79A', 'CD79B', 'CST3', 'LYZ']
    >>> sc.pl.dotplot(adata, markers, groupby='bulk_labels', dendrogram=True)

    Using var_names as dict:
    >>> markers = {{'T-cell': 'CD3D', 'B-cell': 'CD79A', 'myeloid': 'CST3'}}
    >>> sc.pl.dotplot(adata, markers, groupby='bulk_labels', dendrogram=True)

    Get DotPlot object for fine tuning
    >>> dp = sc.pl.dotplot(adata, markers, 'bulk_labels', return_fig=True)
    >>> dp.add_totals().style(dot_edge_color='black', dot_edge_lw=0.5).show()

    The axes used can be obtained using the get_axes() method
    >>> axes_dict = dp.get_axes()

    See also
    --------
    :func:`~scanpy.pl.rank_genes_groups_dotplot`: to plot marker genes
    identified using the :func:`~scanpy.tl.rank_genes_groups` function.
    """

    # backwards compatibily: previous version of dotplot used `color_map`
    # instead of `cmap`
    cmap = kwds.get('color_map', cmap)

    dp = DotPlot(
        adata,
        var_names,
        groupby,
        use_raw=use_raw,
        log=log,
        num_categories=num_categories,
        expression_cutoff=expression_cutoff,
        mean_only_expressed=mean_only_expressed,
        standard_scale=standard_scale,
        title=title,
        figsize=figsize,
        gene_symbols=gene_symbols,
        var_group_positions=var_group_positions,
        var_group_labels=var_group_labels,
        var_group_rotation=var_group_rotation,
        layer=layer,
        dot_color_df=dot_color_df,
        ax=ax,
        **kwds,
    )

    if dendrogram:
        dp.add_dendrogram(dendrogram_key=dendrogram)
    if swap_axes:
        dp.swap_axes()

    dp = dp.style(
        cmap=cmap, dot_max=dot_max, dot_min=dot_min, smallest_dot=smallest_dot,
    ).legend(colorbar_title=colorbar_title, size_title=size_title,)

    if return_fig:
        return dp
    else:
        return dp.show(show=show, save=save)


@_doc_params(
    show_save_ax=doc_show_save_ax,
    common_plot_args=doc_common_plot_args,
    groupby_plots_args=doc_common_groupby_plot_args,
)
def matrixplot(
    adata: AnnData,
    var_names: Union[_VarNames, Mapping[str, _VarNames]],
    groupby: Union[str, Sequence[str]],
    use_raw: Optional[bool] = None,
    log: bool = False,
    num_categories: int = 7,
    figsize: Optional[Tuple[float, float]] = None,
    dendrogram: Union[bool, str] = False,
    title: Optional[str] = None,
    cmap: Optional[str] = MatrixPlot.DEFAULT_COLORMAP,
    colorbar_title: Optional[str] = MatrixPlot.DEFAULT_COLOR_LEGEND_TITLE,
    gene_symbols: Optional[str] = None,
    var_group_positions: Optional[Sequence[Tuple[int, int]]] = None,
    var_group_labels: Optional[Sequence[str]] = None,
    var_group_rotation: Optional[float] = None,
    layer: Optional[str] = None,
    standard_scale: Literal['var', 'group'] = None,
    values_df: Optional[pd.DataFrame] = None,
    swap_axes: bool = False,
    show: Optional[bool] = None,
    save: Union[str, bool, None] = None,
    ax: Optional[_AxesSubplot] = None,
    return_fig: Optional[bool] = False,
    **kwds,
) -> Union[MatrixPlot, dict, None]:
    """\
    Creates a heatmap of the mean expression values per cluster of each var_names.

    This function provides a convenient interface to the :class:`MatrixPlot`
    class. If you need more flexibility, you should use :class:`MatrixPlot` directly.

    Parameters
    ----------
    {common_plot_args}
    {groupby_plots_args}
    {show_save_ax}
    **kwds
        Are passed to :func:`matplotlib.pyplot.pcolor`.

    Returns
    -------
    if `show` is `False`, returns a :class:`MatrixPlot` object

    Examples
    --------
    >>> import scanpy as sc
    >>> adata = sc.datasets.pbmc68k_reduced()
    >>> markers = ['C1QA', 'PSAP', 'CD79A', 'CD79B', 'CST3', 'LYZ']
    >>> sc.pl.matrixplot(adata, markers, groupby='bulk_labels', dendrogram=True)

    Using var_names as dict:
    >>> markers = {{'T-cell': 'CD3D', 'B-cell': 'CD79A', 'myeloid': 'CST3'}}
    >>> sc.pl.matrixplot(adata, markers, groupby='bulk_labels', dendrogram=True)

    Get Matrix object for fine tuning
    >>> mp = sc.pl.matrix(adata, markers, 'bulk_labels', return_fig=True)
    >>> mp.add_totals().style(edge_color='black').show()

    The axes used can be obtained using the get_axes() method
    >>> axes_dict = mp.get_axes()

    See also
    --------
    :func:`~scanpy.pl.rank_genes_groups_matrixplot`: to plot marker genes
    identified using the :func:`~scanpy.tl.rank_genes_groups` function.
    """

    mp = MatrixPlot(
        adata,
        var_names,
        groupby=groupby,
        use_raw=use_raw,
        log=log,
        num_categories=num_categories,
        standard_scale=standard_scale,
        title=title,
        figsize=figsize,
        gene_symbols=gene_symbols,
        var_group_positions=var_group_positions,
        var_group_labels=var_group_labels,
        var_group_rotation=var_group_rotation,
        layer=layer,
        values_df=values_df,
        ax=ax,
        **kwds,
    )

    if dendrogram:
        mp.add_dendrogram(dendrogram_key=dendrogram)
    if swap_axes:
        mp.swap_axes()

    mp = mp.style(cmap=cmap).legend(title=colorbar_title)
    if return_fig:
        return mp
    else:
        return mp.show(show=show, save=save)


@_doc_params(
    show_save_ax=doc_show_save_ax,
    common_plot_args=doc_common_plot_args,
    groupby_plots_args=doc_common_groupby_plot_args,
)
def stacked_violin(
    adata: AnnData,
    var_names: Union[_VarNames, Mapping[str, _VarNames]],
    groupby: Union[str, Sequence[str]],
    log: bool = False,
    use_raw: Optional[bool] = None,
    num_categories: int = 7,
    title: Optional[str] = None,
    colorbar_title: Optional[str] = StackedViolin.DEFAULT_COLOR_LEGEND_TITLE,
    figsize: Optional[Tuple[float, float]] = None,
    dendrogram: Union[bool, str] = False,
    gene_symbols: Optional[str] = None,
    var_group_positions: Optional[Sequence[Tuple[int, int]]] = None,
    var_group_labels: Optional[Sequence[str]] = None,
    standard_scale: Optional[Literal['var', 'obs']] = None,
    var_group_rotation: Optional[float] = None,
    layer: Optional[str] = None,
    stripplot: bool = False,
    jitter: Union[float, bool] = False,
    size: int = 1,
    scale: Literal['area', 'count', 'width'] = 'width',
    order: Optional[Sequence[str]] = None,
    swap_axes: bool = False,
    show: Optional[bool] = None,
    save: Union[bool, str, None] = None,
    return_fig: Optional[bool] = False,
    row_palette: Optional[str] = None,
    cmap: Optional[str] = StackedViolin.DEFAULT_COLORMAP,
    ax: Optional[_AxesSubplot] = None,
    **kwds,
) -> Union[StackedViolin, dict, None]:
    """\
    Stacked violin plots.

    Makes a compact image composed of individual violin plots
    (from :func:`~seaborn.violinplot`) stacked on top of each other.
    Useful to visualize gene expression per cluster.

    Wraps :func:`seaborn.violinplot` for :class:`~anndata.AnnData`.

    This function provides a convenient interface to the :class:`StackedViolin`
    class. If you need more flexibility, you should use :class:`StackedViolin` directly.

    Parameters
    ----------
    {common_plot_args}
    {groupby_plots_args}
    stripplot
        Add a stripplot on top of the violin plot.
        See :func:`~seaborn.stripplot`.
    jitter
        Add jitter to the stripplot (only when stripplot is True)
        See :func:`~seaborn.stripplot`.
    size
        Size of the jitter points.
    order
        Order in which to show the categories. Note: if `dendrogram=True`
        the categories order will be given by the dendrogram and `order`
        will be ignored.
    scale
        The method used to scale the width of each violin.
        If 'width' (the default), each violin will have the same width.
        If 'area', each violin will have the same area.
        If 'count', a violin’s width corresponds to the number of observations.
    row_palette
        Be default, median values are mapped to the violin color using a
        color map (see `cmap` argument). Alternatively, a 'row_palette` can
        be given to color each violin plot row using a different colors.
        The value should be a valid seaborn or matplotlib palette name
        (see :func:`~seaborn.color_palette`).
        Alternatively, a single color name or hex value can be passed,
        e.g. `'red'` or `'#cc33ff'`.
    {show_save_ax}
    **kwds
        Are passed to :func:`~seaborn.violinplot`.

    Returns
    -------
    If `return_fig` is `True`, returns a :class:`StackedViolin` object,
    else if `show` is false, return axes dict

    Examples
    -------
    >>> import scanpy as sc
    >>> adata = sc.datasets.pbmc68k_reduced()
    >>> markers = ['C1QA', 'PSAP', 'CD79A', 'CD79B', 'CST3', 'LYZ']
    >>> sc.pl.stacked_violin(adata, markers, groupby='bulk_labels', dendrogram=True)

    Using var_names as dict:
    >>> markers = {{'T-cell': 'CD3D', 'B-cell': 'CD79A', 'myeloid': 'CST3'}}
    >>> sc.pl.stacked_violin(adata, markers, groupby='bulk_labels', dendrogram=True)

    Get StackedViolin object for fine tuning
    >>> vp = sc.pl.stacked_violin(adata, markers, 'bulk_labels', return_fig=True)
    >>> vp.add_totals().style(ylim=(0,5)).show()

    The axes used can be obtained using the get_axes() method
    >>> axes_dict = vp.get_axes()

    See also
    --------
    rank_genes_groups_stacked_violin: to plot marker genes identified using
    the :func:`~scanpy.tl.rank_genes_groups` function.
    """

    vp = StackedViolin(
        adata,
        var_names,
        groupby=groupby,
        use_raw=use_raw,
        log=log,
        num_categories=num_categories,
        standard_scale=standard_scale,
        title=title,
        figsize=figsize,
        gene_symbols=gene_symbols,
        var_group_positions=var_group_positions,
        var_group_labels=var_group_labels,
        var_group_rotation=var_group_rotation,
        layer=layer,
        ax=ax,
        **kwds,
    )

    if dendrogram:
        vp.add_dendrogram(dendrogram_key=dendrogram)
    if swap_axes:
        vp.swap_axes()
    vp = vp.style(
        cmap=cmap,
        stripplot=stripplot,
        jitter=jitter,
        jitter_size=size,
        row_palette=row_palette,
        scale=scale,
    ).legend(title=colorbar_title)
    if return_fig:
        return vp
    else:
        return vp.show(show=show, save=save)


def _plot_categories_as_colorblocks(
    groupby_ax: Axes,
    obs_tidy: pd.DataFrame,
    colors=None,
    orientation: Literal['top', 'bottom', 'left', 'right'] = 'left',
    cmap_name: str = 'tab20',
):
    """\
    Plots categories as colored blocks. If orientation is 'left', the categories
    are plotted vertically, otherwise they are plotted horizontally.

    Parameters
    ----------
    groupby_ax
    obs_tidy
    colors
        Sequence of valid color names to use for each category.
    orientation
    cmap_name
        Name of colormap to use, in case colors is None

    Returns
    -------
    ticks position, labels, colormap
    """

    groupby = obs_tidy.index.name
    from matplotlib.colors import ListedColormap, BoundaryNorm

    if colors is None:
        groupby_cmap = pl.get_cmap(cmap_name)
    else:
        groupby_cmap = ListedColormap(colors, groupby + '_cmap')
    norm = BoundaryNorm(np.arange(groupby_cmap.N + 1) - 0.5, groupby_cmap.N)

    # determine groupby label positions such that they appear
    # centered next/below to the color code rectangle assigned to the category
    value_sum = 0
    ticks = []  # list of centered position of the labels
    labels = []
    label2code = {}  # dictionary of numerical values asigned to each label
    for code, (label, value) in enumerate(
        obs_tidy.index.value_counts(sort=False).iteritems()
    ):
        ticks.append(value_sum + (value / 2))
        labels.append(label)
        value_sum += value
        label2code[label] = code

    groupby_ax.grid(False)

    if orientation == 'left':
        groupby_ax.imshow(
            np.matrix([label2code[lab] for lab in obs_tidy.index]).T,
            aspect='auto',
            cmap=groupby_cmap,
            norm=norm,
        )
        if len(labels) > 1:
            groupby_ax.set_yticks(ticks)
            groupby_ax.set_yticklabels(labels)

        # remove y ticks
        groupby_ax.tick_params(axis='y', left=False, labelsize='small')
        # remove x ticks and labels
        groupby_ax.tick_params(axis='x', bottom=False, labelbottom=False)

        # remove surrounding lines
        groupby_ax.spines['right'].set_visible(False)
        groupby_ax.spines['top'].set_visible(False)
        groupby_ax.spines['left'].set_visible(False)
        groupby_ax.spines['bottom'].set_visible(False)

        groupby_ax.set_ylabel(groupby)
    else:
        groupby_ax.imshow(
            np.matrix([label2code[lab] for lab in obs_tidy.index]),
            aspect='auto',
            cmap=groupby_cmap,
            norm=norm,
        )
        if len(labels) > 1:
            groupby_ax.set_xticks(ticks)
            if max([len(x) for x in labels]) < 3:
                # if the labels are small do not rotate them
                rotation = 0
            else:
                rotation = 90
            groupby_ax.set_xticklabels(labels, rotation=rotation)

        # remove x ticks
        groupby_ax.tick_params(axis='x', bottom=False, labelsize='small')
        # remove y ticks and labels
        groupby_ax.tick_params(axis='y', left=False, labelleft=False)

        # remove surrounding lines
        groupby_ax.spines['right'].set_visible(False)
        groupby_ax.spines['top'].set_visible(False)
        groupby_ax.spines['left'].set_visible(False)
        groupby_ax.spines['bottom'].set_visible(False)

        groupby_ax.set_xlabel(groupby)

    return ticks, labels, groupby_cmap, norm
